"""패키지별 취약 근거(일치한 보안 공지) 화면. Notion 데이터는 조회만 한다."""

import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, render_template, request

from source.services.processor import SEVERITY_RANK, version_matches_range
from source.services.version_comparison import normalize_ecosystem

ADVISORIES = "NOTION_ADVISORIES_DATA_SOURCE_ID"
SERVICES = "NOTION_SERVICE_DATA_SOURCE_ID"
PACKAGES = "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID"
SOURCES = (SERVICES, PACKAGES, ADVISORIES)

LEVELS = ("critical", "high", "medium", "low")
VIEWS = {"affected": "근거 있음", "unknown": "판정 불가", "mismatch": "저장값과 다름", "all": "전체"}
PAGE_SIZE = 30
KST = timezone(timedelta(hours=9))

evidence_bp = Blueprint("evidence", __name__)


def _normalize(value) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _safe_url(value) -> str | None:
    """http(s) 링크만 허용한다."""
    if isinstance(value, str) and value.strip().lower().startswith(("https://", "http://")):
        return value.strip()
    return None


def _rank(level: str) -> int:
    return SEVERITY_RANK.get(level, 0)


def exit_hint(version_range) -> str | None:
    """취약 범위 상한 기준으로 범위를 벗어나는 버전을 추정한다. (patched version 아님)"""
    if not isinstance(version_range, str):
        return None
    uppers = []
    for condition in version_range.split(","):
        match = re.fullmatch(r"\s*(<=|<|==|=)\s*([0-9]+(?:\.[0-9]+)*)\s*", condition)
        if match:
            uppers.append(match.groups())
    if len(uppers) != 1:
        return None
    operator, boundary = uppers[0]
    return {"<": f"{boundary} 이상", "<=": f"{boundary} 초과"}.get(operator, f"{boundary} 외 버전")


def _unknown_reason(installed, version_range, ecosystem=None) -> str:
    """판정 불가 원인 구분"""
    if version_matches_range(installed, installed, ecosystem=ecosystem) is None:
        return "설치 버전 표기"
    if not isinstance(version_range, str) or not version_range.strip():
        return "공지 범위 없음"
    return "공지 범위 표기"


def _advisory_view(advisory: dict, installed=None, unknown=False) -> dict:
    level = _normalize(advisory.get("severity"))
    return {
        "id": advisory.get("id") or "ID 없음",
        "title": advisory.get("title"),
        "url": _safe_url(advisory.get("url")),
        "cve_id": advisory.get("cve_id") or None,
        "severity": level if level in SEVERITY_RANK else "미확인",
        "range": advisory.get("package_version_range"),
        "published": (advisory.get("published_at") or "")[:10] or None,
        "hint": None if unknown else exit_hint(advisory.get("package_version_range")),
        "reason": _unknown_reason(installed, advisory.get("package_version_range"),
                                  advisory.get("ecosystem")) if unknown else None,
    }


def _dedupe(advisories: list[dict]) -> list[dict]:
    """중복 공지 제거 후 심각도 순 정렬"""
    seen, result = set(), []
    for advisory in advisories:
        key = (advisory.get("id"), advisory.get("package_version_range"))
        if key not in seen:
            seen.add(key)
            result.append(advisory)
    return sorted(result, key=lambda a: -_rank(_normalize(a.get("severity"))))


def build_evidence(services: list[dict], packages: list[dict], advisories: list[dict]) -> list[dict]:
    """패키지별 일치 공지 / 판정 불가 공지 목록을 만든다."""
    # 1. (생태계, 패키지명) 기준으로 공지 그룹화
    by_key = {}
    for advisory in advisories:
        name, ecosystem = advisory.get("package_name"), advisory.get("ecosystem")
        if name and ecosystem:
            by_key.setdefault((normalize_ecosystem(ecosystem), name), []).append(advisory)

    service_by_page = {service.get("page_id"): service for service in services}

    rows = []
    for package in packages:
        installed = package.get("package_version")
        candidates = by_key.get((normalize_ecosystem(package.get("ecosystem")), package.get("package_name")), [])
        matched, unknown = [], []
        for advisory in candidates:
            result = version_matches_range(installed, advisory.get("package_version_range"),
                                           ecosystem=package.get("ecosystem"))
            if result is None:
                unknown.append(advisory)
            elif result:
                matched.append(advisory)
        matched, unknown = _dedupe(matched), _dedupe(unknown)

        # 2. 판정: 일치 공지 최고 심각도 > unknown > safe (processor.py 와 동일)
        levels = [_normalize(a.get("severity")) for a in matched]
        levels = [level for level in levels if level in SEVERITY_RANK]
        if levels:
            computed = max(levels, key=_rank)
        elif unknown or matched:
            # 일치 공지의 severity 가 모두 unknown 인 경우 포함
            computed = "unknown"
        else:
            computed = "safe"

        stored = _normalize(package.get("vulnerability"))
        mismatch = (stored or "safe") != computed
        rows.append({
            "page_id": package.get("page_id"),
            "package_id": package.get("id"),
            "package_name": package.get("package_name"),
            "ecosystem": package.get("ecosystem"),
            "installed_version": installed,
            "services": [
                {"id": service_by_page.get(pid, {}).get("id"),
                 "name": service_by_page.get(pid, {}).get("resource_name") or "서비스 확인 필요"}
                for pid in package.get("service_id") or []
            ],
            "stored": stored or "미설정",
            "computed": computed,
            "mismatch": mismatch,
            # 전체 재분석은 비교가 가능해진 기존 unknown을 safe로 갱신할 수 있다.
            "mismatch_fixable": mismatch and (computed != "safe" or (stored == "unknown" and bool(candidates))),
            "candidate_count": len(candidates),
            "matched": [_advisory_view(a) for a in matched],
            "unknown": [_advisory_view(a, installed, unknown=True) for a in unknown],
        })

    # 3. 정렬: 심각도 → 일치 공지 수 → 이름
    rows.sort(key=lambda row: (-_rank(row["computed"]), -len(row["matched"]),
                               row["package_name"] or "", row["package_id"] or ""))
    return rows


def summarize(rows: list[dict]) -> dict:
    """요약 수치와 서비스별 위험 집계"""
    counts = {level: 0 for level in (*LEVELS, "unknown", "safe")}
    services = {}
    for row in rows:
        counts[row["computed"]] += 1
        for service in row["services"] or [{"id": None, "name": "서비스 미연결"}]:
            key = service["id"] or service["name"]
            entry = services.setdefault(key, {"id": service["id"], "name": service["name"],
                                              **{level: 0 for level in LEVELS}, "unknown": 0})
            if row["computed"] in entry:
                entry[row["computed"]] += 1

    service_list = [s for s in services.values() if any(s[level] for level in (*LEVELS, "unknown"))]
    # critical → high → medium → low 개수 순 정렬
    service_list.sort(key=lambda s: tuple(-s[level] for level in LEVELS) + (-s["unknown"], s["id"] or ""))
    widest = max((sum(s[level] for level in (*LEVELS, "unknown")) for s in service_list), default=0)
    for service in service_list:
        total = sum(service[level] for level in (*LEVELS, "unknown"))
        service["total"] = total
        service["segments"] = [
            {"level": level, "count": service[level],
             "width": round(service[level] / widest * 100, 2)}
            for level in (*LEVELS, "unknown") if service[level]
        ]
    return {
        "counts": counts,
        "affected": sum(counts[level] for level in LEVELS),
        "matched_total": sum(len(row["matched"]) for row in rows),
        "mismatch": sum(row["mismatch"] for row in rows),
        "services": service_list,
    }


def filter_evidence(rows: list[dict], view: str, query: str = "", service: str = "") -> list[dict]:
    if view == "affected":
        rows = [row for row in rows if row["matched"]]
    elif view == "unknown":
        rows = [row for row in rows if row["computed"] == "unknown"]
    elif view == "mismatch":
        rows = [row for row in rows if row["mismatch"]]
    if service:
        rows = [row for row in rows if any(s["id"] == service for s in row["services"])]
    if query:
        q = query.lower()
        rows = [row for row in rows
                if q in (row["package_name"] or "").lower()
                or q in (row["package_id"] or "").lower()
                or any(q in (a["cve_id"] or "").lower() or q in (a["id"] or "").lower()
                       for a in row["matched"] + row["unknown"])]
    return rows


def _format_time(value) -> str | None:
    try:
        return datetime.fromisoformat(value).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


@evidence_bp.get("/evidence")
def evidence_page():
    cache = current_app.extensions["dashboard_cache"]
    state = cache.ensure(SOURCES, force=request.args.get("refresh") == "1")
    if not state["ready"]:
        # 첫 조회 중이면 로딩 화면 (3초 후 새로고침)
        return render_template("evidence.html", loading=True, failed=state["failed"])

    rows = build_evidence(cache.read(SERVICES), cache.read(PACKAGES), cache.read(ADVISORIES))
    summary = summarize(rows)

    view = request.args.get("view", "affected")
    view = view if view in VIEWS else "affected"
    query = request.args.get("q", "").strip()[:100]
    service = request.args.get("service", "").strip()[:50]
    service_name = next((s["name"] for s in summary["services"] if s["id"] == service), None)
    if service and service_name is None:
        service = ""

    counts = {key: len(filter_evidence(rows, key, query, service)) for key in VIEWS}
    visible = filter_evidence(rows, view, query, service)
    page_count = max(1, -(-len(visible) // PAGE_SIZE))
    page = min(max(1, request.args.get("page", 1, type=int)), page_count)
    start = (page - 1) * PAGE_SIZE

    def link(**changes):
        """현재 필터를 유지한 URL 파라미터"""
        params = {"view": view, "q": query, "service": service, "page": None, **changes}
        return {key: value for key, value in params.items() if value}

    return render_template(
        "evidence.html", loading=False, summary=summary,
        rows=visible[start:start + PAGE_SIZE], total=len(visible), start=start,
        page=page, page_count=page_count, link=link,
        view=view, views=VIEWS, counts=counts, query=query,
        service=service, service_name=service_name, levels=LEVELS,
        package_count=len(rows), updated_at=_format_time(state["updated_at"]),
        stale=state["failed"] or state["stale"],
    )
