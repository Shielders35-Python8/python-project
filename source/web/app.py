"""프로젝트 실행과 결과 조회를 위한 Flask 웹 대시보드.

프로젝트 루트에서 실행: python -m source.web.app
개발 모드: python -m flask --app source.web.app run --debug
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, current_app, g, has_app_context, jsonify, render_template, request, url_for

# README에 안내한 파일 직접 실행 방식도 패키지 import가 가능하게 한다.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from source.common.notion.notion import NotionClient
from source.common.notion.query_policy import NotionQueryPolicy
from source.common.slack.notifications import init_app
from source.config.config import get_env
from source.services.advisory_analysis import analyze_advisories, validate_advisory_period
from source.services.processor import evaluate_impact
from source.services.advisory_sync import sync_advisories_to_notion
from source.web.advisory_sync_runs import AdvisorySyncRuns
from source.web.analysis_runs import AnalysisRuns
from source.web.dashboard_data import (
    RESULT_SEVERITY_FILTERS, build_saved_package_results, filter_saved_package_results,
)
from source.web.advisory_list import build_saved_advisories
from source.web.data_cache import DashboardDataCache


ADVISORIES = "NOTION_ADVISORIES_DATA_SOURCE_ID"
SERVICES = "NOTION_SERVICE_DATA_SOURCE_ID"
PACKAGES = "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID"
PAGE_SOURCES = {
    "dashboard": (SERVICES, PACKAGES, ADVISORIES),
    "results": (SERVICES, PACKAGES),
    "security_advisories": (ADVISORIES,),
    "advisories": (ADVISORIES,),
}
PAGE_TITLES = {
    "dashboard": "보안 공지 대시보드", "results": "분석 결과",
    "security_advisories": "보안 공지", "advisories": "공지 분석",
}
ENDPOINT_PAGES = {
    "dashboard": "dashboard", "analysis_results": "results", "get_results": "results",
    "security_advisories": "security_advisories", "advisory_list_api": "security_advisories",
    "advisory_dashboard": "advisories", "advisory_analysis_api": "advisories",
}


def get_saved_rows(env_key: str) -> list[dict]:
    if has_app_context() and current_app.config["DASHBOARD_CACHE_ENABLED"]:
        return current_app.extensions["dashboard_cache"].read(env_key)
    return fetch_saved_rows(env_key)


def fetch_saved_rows(env_key: str, query_policy=None) -> list[dict]:
    data_source_id = get_env(env_key).strip()
    if not data_source_id:
        raise ValueError("Notion 데이터 소스 ID가 필요합니다.")
    options = {"timeout_ms": 15_000, "query_policy": query_policy} if query_policy else {}
    client = NotionClient(**options)
    try:
        return client.get_database_rows(data_source_id=data_source_id)
    finally:
        client.client.close()


def get_saved_advisory_analysis(*, started_at=None, ended_at=None) -> dict:
    """Notion 공지 전체를 조회해 게시일 범위에 맞는 통계를 반환한다."""
    # 입력 오류는 Notion 요청을 보내기 전에 확인한다.
    validate_advisory_period(started_at=started_at, ended_at=ended_at)
    return analyze_advisories(
        get_saved_rows("NOTION_ADVISORIES_DATA_SOURCE_ID"),
        started_at=started_at, ended_at=ended_at,
    )


def create_app(config=None) -> Flask:
    """웹 앱을 생성한다. 서버 시작 시 공지 수집을 실행하지 않는다."""
    app = Flask(__name__)
    app.config.from_mapping(
        DASHBOARD_CACHE_ENABLED=True, DASHBOARD_CACHE_TTL=60,
        TEMPLATES_AUTO_RELOAD=True,
    )
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False
    init_app(app)
    query_policy = NotionQueryPolicy()
    cache = DashboardDataCache(lambda key: fetch_saved_rows(key, query_policy),
                               ttl=app.config["DASHBOARD_CACHE_TTL"])
    app.extensions["dashboard_cache"] = cache
    runs = AnalysisRuns(
        lambda progress: evaluate_impact(None, None, progress=progress, query_policy=query_policy),
        lambda: cache.invalidate((PACKAGES,)),
    )
    app.extensions["analysis_runs"] = runs
    sync_runs = AdvisorySyncRuns(
        lambda dates, progress: sync_advisories_to_notion(dates, progress=progress, query_policy=query_policy),
        lambda: cache.invalidate((ADVISORIES,)),
    )
    app.extensions["advisory_sync_runs"] = sync_runs

    @app.before_request
    def prepare_saved_data():
        page = ENDPOINT_PAGES.get(request.endpoint)
        if not app.config["DASHBOARD_CACHE_ENABLED"] or page is None:
            return None
        if page == "advisories":
            try:
                validate_advisory_period(started_at=request.args.get("started_at"),
                                         ended_at=request.args.get("ended_at"))
            except ValueError:
                return None  # 기존 400 응답을 사용하고 잘못된 입력으로 조회를 시작하지 않는다.
        g.cache_page = page
        g.cache_state = cache.ensure(PAGE_SOURCES[page], force=request.args.get("refresh") == "1")
        if g.cache_state["loading"]:
            if request.path.startswith("/api/"):
                return jsonify(status="loading", source="notion", cache=g.cache_state), 202, {"Retry-After": "2"}
            return render_template("index.html", active_page=page, page_title=PAGE_TITLES[page],
                                   page_description="저장된 데이터를 준비하고 있습니다.", cache_loading=True)

    @app.context_processor
    def saved_data_context():
        today = datetime.now(timezone.utc).date()
        values = {key: request.args[key] for key in ("severity", "page", "started_at", "ended_at")
                  if key in request.args}
        values["refresh"] = "1"
        return {
            "analysis_state": runs.snapshot(),
            "sync_state": sync_runs.snapshot(),
            "sync_default_start": (today - timedelta(days=6)).isoformat(),
            "sync_default_end": today.isoformat(),
            "cache_state": getattr(g, "cache_state", None),
            "cache_page": getattr(g, "cache_page", None),
            "cache_refresh_url": url_for(request.endpoint, **values) if request.endpoint in ENDPOINT_PAGES else None,
        }

    @app.after_request
    def saved_data_headers(response):
        if getattr(g, "cache_page", None) or request.endpoint in (
            "cache_status", "analysis_run_status", "run_project", "collect_advisories", "advisory_sync_status",
        ):
            response.headers["Cache-Control"] = "no-store"
            if response.is_json and getattr(g, "cache_state", None):
                body = response.get_json()
                body["cache"] = g.cache_state
                response.set_data(app.json.dumps(body))
        return response

    @app.get("/api/cache-status")
    def cache_status():
        page = request.args.get("view", "dashboard")
        if page not in PAGE_SOURCES:
            return jsonify(status="error", message="알 수 없는 화면입니다."), 400
        # 상태 확인 자체는 Notion 요청이나 새 작업을 발생시키지 않는다.
        return jsonify(cache.status(PAGE_SOURCES[page]))

    def load_service_results():
        data = {
            "service_count": None, "service_error": None,
            "results": [], "results_error": None,
            "package_count": None, "affected_count": None,
            "safe_count": None, "unknown_count": None,
        }
        services = []
        try:
            services = get_saved_rows("NOTION_SERVICE_DATA_SOURCE_ID")
            data["service_count"] = len(services)
        except Exception as error:
            app.logger.warning("Notion 서비스 조회 실패: %s", type(error).__name__)
            data["service_error"] = "Notion 서비스 조회 실패 · 새로고침해 주세요."
        try:
            packages = get_saved_rows("NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID")
            results = build_saved_package_results(services, packages)
            data.update(
                results=results,
                package_count=len(results),
                affected_count=sum(result["is_affected"] for result in results),
                safe_count=sum(result["status_kind"] == "safe" for result in results),
                unknown_count=sum(result["status_kind"] == "unknown" for result in results),
            )
        except Exception as error:
            app.logger.warning("Notion 패키지 취약도 조회 실패: %s", type(error).__name__)
            data["results_error"] = "Notion 패키지 취약도 조회 실패 · 새로고침해 주세요."
        return data

    def render_dashboard_page(active_page: str):
        page_content = {
            "dashboard": (
                "보안 공지 대시보드",
                "보안 공지와 서비스별 패키지를 살펴보고, 취약점의 영향을 확인합니다.",
            ),
            "run_status": (
                "실행 상태",
                "저장된 Notion 공지의 취약도 분석과 결과 저장 상태를 확인합니다.",
            ),
            "results": (
                "분석 결과",
                "Notion에 저장된 서비스별 패키지와 취약도를 확인합니다.",
            ),
        }
        title, description = page_content[active_page]
        advisory_count = None
        advisory_error = None
        analysis = None
        if active_page == "dashboard":
            try:
                analysis = get_saved_advisory_analysis()
                advisory_count = analysis["summary"]["advisory_count"]
            except Exception as error:
                app.logger.warning("Notion 공지 조회 실패: %s", type(error).__name__)
                advisory_error = "Notion 공지 조회 실패 · 새로고침해 주세요."
        service_data = load_service_results() if active_page in ("dashboard", "results") else {}
        filtered = filter_saved_package_results(
            service_data.get("results", []),
            request.args.get("severity") if active_page == "results" else None,
        )
        results = filtered["results"]
        selected_severity = filtered["severity"]
        page_size = 50
        page_count = max(1, (len(results) + page_size - 1) // page_size)
        page = min(max(1, request.args.get("page", 1, type=int)), page_count)
        return render_template(
            "index.html",
            **service_data,
            result_severity=selected_severity,
            result_severity_label=RESULT_SEVERITY_FILTERS[selected_severity],
            filtered_result_count=len(results) if not service_data.get("results_error") else None,
            result_filter_options=[{
                "value": value, "label": label,
                "count": filtered["counts"][value] if not service_data.get("results_error") else None,
            } for value, label in RESULT_SEVERITY_FILTERS.items()],
            visible_results=results[(page - 1) * page_size:page * page_size],
            result_page=page,
            result_page_count=page_count,
            result_start=(page - 1) * page_size,
            advisory_count=advisory_count,
            advisory_error=advisory_error,
            analysis=analysis,
            active_page=active_page,
            page_title=title,
            page_description=description,
        )

    @app.get("/")
    def dashboard():
        return render_dashboard_page("dashboard")

    @app.get("/run-status")
    def run_status():
        return render_dashboard_page("run_status")

    @app.get("/results")
    def analysis_results():
        return render_dashboard_page("results")

    def load_advisory_analysis():
        filters = {
            "started_at": request.args.get("started_at", ""),
            "ended_at": request.args.get("ended_at", ""),
        }
        try:
            validate_advisory_period(**filters)
        except ValueError as error:
            return None, str(error), filters, 400
        try:
            return get_saved_advisory_analysis(**filters), None, filters, 200
        except Exception as error:
            app.logger.warning("Notion 공지 분석 조회 실패: %s", type(error).__name__)
            return None, "Notion 공지를 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.", filters, 503

    @app.get("/advisories")
    def advisory_dashboard():
        analysis, error, filters, status = load_advisory_analysis()
        return render_template(
            "index.html", active_page="advisories", page_title="공지 분석",
            page_description="Notion에 저장된 보안 공지의 심각도, 생태계와 게시 추이를 살펴봅니다.",
            analysis=analysis, analysis_error=error, filters=filters,
        ), status

    @app.get("/api/advisories/analysis")
    def advisory_analysis_api():
        analysis, error, filters, status = load_advisory_analysis()
        return jsonify(
            status="ok" if status == 200 else "error", source="notion",
            analysis=analysis, message=error, filters=filters,
        ), status

    def load_advisory_list():
        try:
            rows = get_saved_rows("NOTION_ADVISORIES_DATA_SOURCE_ID")
            advisories = build_saved_advisories(rows)
            return {
                "advisories": advisories, "advisory_count": len(advisories),
                "advisory_row_count": len(rows), "advisory_error": None,
            }
        except Exception as error:
            app.logger.warning("Notion 공지 목록 조회 실패: %s", type(error).__name__)
            return {
                "advisories": [], "advisory_count": None, "advisory_row_count": None,
                "advisory_error": "Notion 공지 조회 실패 · 새로고침해 주세요.",
            }

    @app.get("/advisories/list")
    def security_advisories():
        data = load_advisory_list()
        page_size = 50
        page_count = max(1, (len(data["advisories"]) + page_size - 1) // page_size)
        page = min(max(1, request.args.get("page", 1, type=int)), page_count)
        start = (page - 1) * page_size
        return render_template(
            "index.html", active_page="security_advisories", page_title="보안 공지",
            page_description="Notion에 저장된 보안 공지와 패키지별 취약 버전 범위를 확인합니다.",
            **data, visible_advisories=data["advisories"][start:start + page_size],
            advisory_page=page, advisory_page_count=page_count, advisory_start=start,
        )

    @app.get("/api/advisories")
    def advisory_list_api():
        data = load_advisory_list()
        return jsonify(
            status="error" if data["advisory_error"] else "ok", source="notion", **data,
        ), 503 if data["advisory_error"] else 200

    @app.get("/api/health")
    def health():
        """웹 서버의 응답 여부만 확인한다. 외부 서비스 상태는 포함하지 않는다."""
        return jsonify(status="ok", service="project-dashboard")

    @app.get("/api/results")
    def get_results():
        data = load_service_results()
        filtered = filter_saved_package_results(data["results"], request.args.get("severity"))
        data["results"] = filtered["results"]
        status = "error" if data["results_error"] else "partial" if data["service_error"] else "ok"
        return jsonify(
            status=status,
            source="notion",
            result_type="saved_package_vulnerability",
            severity=filtered["severity"],
            filtered_count=len(data["results"]) if not data["results_error"] else None,
            severity_counts=filtered["counts"] if not data["results_error"] else None,
            message=data["results_error"] or data["service_error"] or "Notion에 저장된 패키지 취약도입니다.",
            **data,
        ), 503 if data["results_error"] else 200

    @app.post("/api/run")
    def run_project():
        # JSON과 같은 출처의 요청만 허용하여 외부 페이지의 폼 제출로 실행되지 않게 한다.
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and origin != request.host_url.rstrip("/")):
            return jsonify(status="error", message="같은 대시보드에서 분석을 실행해 주세요."), 403
        if not request.is_json:
            return jsonify(status="error", message="JSON 형식의 실행 요청이 필요합니다."), 415
        if request.args or request.get_json(silent=True) != {}:
            return jsonify(status="error", message="저장된 전체 Notion 공지만 분석할 수 있습니다. 빈 JSON 객체를 보내 주세요."), 400
        try:
            started, run = runs.start()
        except Exception as error:
            app.logger.warning("분석 작업 시작 실패: %s", type(error).__name__)
            return jsonify(status="error", message="분석을 시작하지 못했습니다. 잠시 후 다시 실행해 주세요."), 503
        return jsonify(status="accepted" if started else "busy", run=run), 202 if started else 409

    @app.get("/api/run-status")
    def analysis_run_status():
        return jsonify(**runs.snapshot())

    @app.post("/api/advisories/sync")
    def collect_advisories():
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and origin != request.host_url.rstrip("/")):
            return jsonify(status="error", message="같은 대시보드에서 공지를 수집해 주세요."), 403
        if not request.is_json:
            return jsonify(status="error", message="JSON 형식의 실행 요청이 필요합니다."), 415
        payload = request.get_json(silent=True)
        if request.args or not isinstance(payload, dict) or set(payload) != {"started_at", "ended_at"}:
            return jsonify(status="error", message="수집 시작일과 종료일을 입력해 주세요."), 400
        try:
            start, end = validate_advisory_period(**payload)
            if start is None or end is None:
                raise ValueError("수집 시작일과 종료일을 모두 입력해 주세요.")
        except ValueError as error:
            return jsonify(status="error", message=str(error)), 400
        try:
            started, run = sync_runs.start(start.isoformat(), end.isoformat())
        except Exception as error:
            app.logger.warning("공지 수집 시작 실패: %s", type(error).__name__)
            return jsonify(status="error", message="수집을 시작하지 못했습니다. 잠시 후 다시 실행해 주세요."), 503
        return jsonify(status="accepted" if started else "busy", run=run), 202 if started else 409

    @app.get("/api/advisories/sync-status")
    def advisory_sync_status():
        return jsonify(**sync_runs.snapshot())

    # 취약 근거 화면 (읽기 전용) — source/web/evidence.py
    from source.web.evidence import evidence_bp
    app.register_blueprint(evidence_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
