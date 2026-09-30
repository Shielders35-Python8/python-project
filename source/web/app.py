"""프로젝트 실행과 결과 조회를 위한 Flask 웹 대시보드.

프로젝트 루트에서 실행: python -m source.web.app
개발 모드: python -m flask --app source.web.app run --debug
"""

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# README에 안내한 파일 직접 실행 방식도 패키지 import가 가능하게 한다.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from source.common.notion.notion import NotionClient
from source.common.slack.notifications import init_app
from source.config.config import get_env
from source.services.advisory_analysis import advisory_key, analyze_advisories, validate_advisory_period
from source.web.dashboard_data import build_saved_package_results
from source.web.advisory_list import build_saved_advisories


def get_saved_rows(env_key: str) -> list[dict]:
    data_source_id = get_env(env_key).strip()
    if not data_source_id:
        raise ValueError("Notion 데이터 소스 ID가 필요합니다.")
    return NotionClient().get_database_rows(data_source_id=data_source_id)


def get_saved_advisory_count() -> int:
    """Notion의 패키지·버전별 행을 공지 ID 기준으로 중복 집계하지 않는다."""
    advisories = get_saved_rows("NOTION_ADVISORIES_DATA_SOURCE_ID")
    return len({advisory_key(row, index) for index, row in enumerate(advisories)})


def get_saved_advisory_analysis(*, started_at=None, ended_at=None) -> dict:
    """Notion 공지 전체를 조회해 게시일 범위에 맞는 통계를 반환한다."""
    # 입력 오류는 Notion 요청을 보내기 전에 확인한다.
    validate_advisory_period(started_at=started_at, ended_at=ended_at)
    return analyze_advisories(
        get_saved_rows("NOTION_ADVISORIES_DATA_SOURCE_ID"),
        started_at=started_at, ended_at=ended_at,
    )


def create_app() -> Flask:
    """웹 앱을 생성한다. 서버 시작 시 공지 수집을 실행하지 않는다."""
    app = Flask(__name__)
    app.json.ensure_ascii = False
    init_app(app)

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
                "보안 공지 수집부터 분석, 저장까지 실행 상태와 기록을 확인합니다.",
            ),
            "results": (
                "분석 결과",
                "Notion에 저장된 서비스별 패키지와 취약도를 확인합니다.",
            ),
        }
        title, description = page_content[active_page]
        advisory_count = None
        advisory_error = None
        if active_page == "dashboard":
            try:
                advisory_count = get_saved_advisory_count()
            except Exception as error:
                app.logger.warning("Notion 공지 조회 실패: %s", type(error).__name__)
                advisory_error = "Notion 공지 조회 실패 · 새로고침해 주세요."
        service_data = load_service_results() if active_page in ("dashboard", "results") else {}
        results = service_data.get("results", [])
        page_size = 50
        page_count = max(1, (len(results) + page_size - 1) // page_size)
        page = min(max(1, request.args.get("page", 1, type=int)), page_count)
        return render_template(
            "index.html",
            **service_data,
            visible_results=results[(page - 1) * page_size:page * page_size],
            result_page=page,
            result_page_count=page_count,
            result_start=(page - 1) * page_size,
            advisory_count=advisory_count,
            advisory_error=advisory_error,
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
        status = "error" if data["results_error"] else "partial" if data["service_error"] else "ok"
        return jsonify(
            status=status,
            source="notion",
            result_type="saved_package_vulnerability",
            message=data["results_error"] or data["service_error"] or "Notion에 저장된 패키지 취약도입니다.",
            **data,
        ), 503 if data["results_error"] else 200

    @app.post("/api/run")
    def run_project():
        # TODO: 수집 → 분석 → 저장 작업을 연결한다.
        # 장시간 작업은 요청 안에서 직접 실행하지 않는다.
        return jsonify(
            status="not_implemented",
            message="프로젝트 실행 기능이 아직 연결되지 않았습니다.",
        ), 501

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
