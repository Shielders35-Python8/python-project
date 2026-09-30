"""Notion에 저장된 패키지 취약도를 화면용으로 정리한다. 분석이나 저장은 실행하지 않는다."""

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


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
