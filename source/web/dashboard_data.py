"""Notion에 저장된 패키지 취약도를 화면용으로 정리한다. 분석이나 저장은 실행하지 않는다."""

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
RESULT_SEVERITY_FILTERS = {
    "all": "전체", "critical": "critical", "high": "high", "medium": "medium",
    "low": "low", "safe": "safe", "unknown": "알 수 없음/기타",
}
RESULT_SEARCH_FIELDS = {
    "all": "전체 항목", "package_name": "패키지명", "package_id": "패키지 ID",
    "service_name": "서비스명", "business_domain": "비즈니스 도메인", "ecosystem": "생태계",
}


def filter_saved_package_results(
    results: list[dict], severity: str | None = None, service: str | None = None,
    q: str | None = None, search_field: str | None = None,
) -> dict:
    """전체 저장값의 등급별 건수를 유지하며 페이지를 나누기 전에 필터링한다."""
    selected = (severity or "all").strip().lower()
    if selected not in RESULT_SEVERITY_FILTERS:
        selected = "all"
    counts = dict.fromkeys(RESULT_SEVERITY_FILTERS, 0)
    counts["all"] = len(results)
    selected_service = (service or "").strip()
    query = (q or "").strip()
    search_term = query.casefold()
    selected_field = (search_field or "all").strip().lower()
    if selected_field not in RESULT_SEARCH_FIELDS:
        selected_field = "all"
    service_counts = dict.fromkeys(RESULT_SEVERITY_FILTERS, 0)
    search_counts = dict.fromkeys(RESULT_SEVERITY_FILTERS, 0)
    filtered = []
    for result in results:
        value = (result.get("vulnerability") or "").strip().lower()
        bucket = value if value in SEVERITY_ORDER or value == "safe" else "unknown"
        counts[bucket] += 1
        linked_services = result.get("services") or []
        if selected_service == "unlinked":
            matches_service = not linked_services
        else:
            matches_service = not selected_service or any(
                item["page_id"] == selected_service for item in linked_services
            )
        if not matches_service:
            continue
        service_counts["all"] += 1
        service_counts[bucket] += 1
        if search_term:
            fields = {
                "package_name": [result.get("package_name")],
                "package_id": [result.get("package_id")],
                "ecosystem": [result.get("ecosystem")],
                "service_name": [item.get("name") for item in linked_services],
                "business_domain": [item.get("business_domain") for item in linked_services],
            }
            values = (value for key, items in fields.items()
                      if selected_field == "all" or key == selected_field for value in items)
            if not any(search_term in (value or "").casefold() for value in values):
                continue
        search_counts["all"] += 1
        search_counts[bucket] += 1
        if selected == "all" or selected == bucket:
            filtered.append(result)
    return {
        "severity": selected, "service": selected_service, "results": filtered,
        "q": query, "search_field": selected_field,
        "counts": counts, "service_counts": service_counts, "search_counts": search_counts,
    }


def build_result_service_options(
    services: list[dict], results: list[dict], selected_service: str | None = None,
) -> list[dict]:
    """서비스명·도메인을 표시하고, 필터 값은 안정적인 관계 페이지 ID를 쓴다."""
    def display_label(service):
        name = service.get("resource_name") or service.get("name") or "서비스 확인 필요"
        domain = (service.get("business_domain") or "").strip()
        return f"{name} · {domain}" if domain else name

    names = {service["page_id"]: display_label(service) for service in services}
    for result in results:
        for service in result["services"]:
            names.setdefault(service["page_id"], display_label(service))
    selected_service = (selected_service or "").strip()
    if selected_service and selected_service != "unlinked":
        # 삭제된 서비스의 링크나 서비스 조회 실패도 필터를 전체로 바꾸지 않는다.
        names.setdefault(selected_service, "서비스 확인 필요")
    return [{"value": "", "label": "전체 서비스"}] + [
        {"value": page_id, "label": name}
        for page_id, name in sorted(names.items(), key=lambda item: (item[1].casefold(), item[0]))
    ] + [{"value": "unlinked", "label": "서비스 미연결"}]


def build_saved_package_results(services: list[dict], packages: list[dict]) -> list[dict]:
    service_by_page = {service["page_id"]: service for service in services}
    results = []
    for package in packages:
        linked_services = []
        for page_id in package.get("service_id") or []:
            service = service_by_page.get(page_id, {})
            linked_services.append({
                "page_id": page_id,
                "id": service.get("id"),
                "name": service.get("resource_name") or "서비스 확인 필요",
                "business_domain": (service.get("business_domain") or "").strip(),
            })
        vulnerability = package.get("vulnerability")
        severity = (vulnerability or "").strip().lower()
        results.append({
            "package_id": package.get("id"),
            "page_id": package.get("page_id"),
            "services": linked_services,
            "package_name": package.get("package_name"),
            "ecosystem": package.get("ecosystem"),
            "installed_version": package.get("package_version"),
            "vulnerability": vulnerability,
            "vulnerability_label": "알 수 없음" if severity == "unknown" else (vulnerability or "미설정"),
            "is_affected": severity in SEVERITY_ORDER,
            "status_kind": "affected" if severity in SEVERITY_ORDER else (
                "safe" if severity == "safe" else "unknown"
            ),
        })
    # 취약도가 높은 항목과 미설정 항목을 먼저 보여주며 서비스 관계 수로 행을 늘리지 않는다.
    results.sort(key=lambda result: (
        SEVERITY_ORDER.get((result["vulnerability"] or "").strip().lower(),
                           5 if result["status_kind"] == "safe" else 4),
        result["package_name"] or "",
        result["package_id"] or "",
        result["page_id"] or "",
    ))
    return results
