import re

from source.common.notion.notion import NotionClient
from source.config.config import get_env
from source.common.slack.notifications import notify_errors
from source.common.slack.slack import send_task_message


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def version_matches_range(version, version_range) -> bool | None:
    """숫자 버전의 범위 포함 여부. 지원하지 않는 표기는 None(알 수 없음)이다."""
    if not isinstance(version, str) or not isinstance(version_range, str):
        return None
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version.strip()) is None:
        return None

    # 모든 조건을 먼저 읽어, 조건 순서에 따라 판정 불가가 False로 바뀌지 않게 한다.
    conditions = []
    for condition in version_range.split(","):
        match = re.fullmatch(
            r"\s*(<=|>=|==|!=|<|>|=)?\s*([0-9]+(?:\.[0-9]+)*)\s*",
            condition,
        )
        if match is None:
            return None
        operator, boundary = match.groups()
        conditions.append((operator or "==", tuple(map(int, boundary.split(".")))))

    installed = tuple(map(int, version.strip().split(".")))
    for operator, limit in conditions:
        length = max(len(installed), len(limit))
        # 1.2와 1.2.0을 같은 버전으로 비교한다.
        current = installed + (0,) * (length - len(installed))
        limit += (0,) * (length - len(limit))
        comparisons = {
            "<": current < limit, "<=": current <= limit,
            ">": current > limit, ">=": current >= limit,
            "=": current == limit, "==": current == limit, "!=": current != limit,
        }
        if not comparisons[operator]:
            return False
    return True


@notify_errors("취약도 분석")
def evaluate_impact(started_at, ended_at, *, progress=None, query_policy=None):
    """노션 db에서 가져온 service-package테이블의 데이터와 advisories테이블의 데이터를 비교한다
    각 advisories 마다 "package_name", "package_version_range", "ecosystem" 과 service_package의 "package_name", "package_version", "ecosystem"을 비교하고
    분석 대상 공지 중 일치한 가장 높은 severity로 패키지별 vulnerability를 한 번만 업데이트한다.
    취약점 일치는 없지만 같은 패키지의 버전 비교에 실패하면 unknown으로 저장한다.
    """
    notion = NotionClient(query_policy=query_policy) if query_policy else NotionClient()
    try:
        return _evaluate_impact(notion, started_at, ended_at, progress or (lambda **values: None))
    finally:
        notion.client.close()


def _evaluate_impact(notion, started_at, ended_at, progress):
    progress(stage="loading", message="저장된 Notion 공지와 패키지를 불러오고 있습니다.")

    # 1. start_at과 end_at을 notion.py의 def get_database_rows 에 넣고, 먼저 'advisories' 테이블의 데이터들을 가져온다.
    advisories = notion.get_database_rows(
        data_source_id=get_env("NOTION_ADVISORIES_DATA_SOURCE_ID"),
        date_column="updated_at",
        started_at=started_at,
        ended_at=ended_at,
    )

    # 2.  notion.py의 def get_database_rows 로 service_package의 데이터들을 가져온다.
    service_packages = notion.get_database_rows(
        data_source_id=get_env("NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID"),
    )
    summary = {"advisory_count": len(advisories), "package_count": len(service_packages),
               "matched_count": 0, "affected_count": 0, "unknown_count": 0,
               "total_updates": 0, "updated_count": 0}
    progress(stage="comparing", message="패키지 버전과 취약 범위를 비교하고 있습니다.", **summary)

    # 3. advisories와 service_packages의 칼럼을 비교해서 일치하는 경우를 찾는다. 3칼럼 모두 같아야함. package_version과
    # package_version_range는 범위 비교 필요.
    matches = []
    unknown_packages = set()
    for advisory in advisories:
        if not advisory.get("package_name") or not advisory.get("ecosystem"):
            continue
        for service_package in service_packages:
            if advisory["package_name"] != service_package.get(
                "package_name"
            ) or advisory["ecosystem"] != service_package.get("ecosystem"):
                continue
            is_match = version_matches_range(
                service_package.get("package_version"),
                advisory.get("package_version_range"),
            )
            if is_match is None:
                unknown_packages.add(service_package["page_id"])
            elif is_match:
                matches.append(
                    {"advisory": advisory, "service_package": service_package}
                )

    # 4. 공지 순서와 관계없이 패키지별 최고 심각도를 정한 뒤 한 번씩 저장한다.
    highest_severity_by_page = {}
    for match in matches:
        page_id = match["service_package"]["page_id"]
        value = match["advisory"].get("severity")
        severity = value.strip().lower() if isinstance(value, str) else ""
        if severity not in SEVERITY_RANK:
            raise ValueError("일치한 공지의 severity는 low, medium, high, critical 중 하나여야 합니다.")
        previous = highest_severity_by_page.get(page_id)
        if previous is None or SEVERITY_RANK[severity] > SEVERITY_RANK[previous]:
            highest_severity_by_page[page_id] = severity

    # 확인된 취약점은 숨기지 않는다. 판정 불가만 있는 패키지를 unknown으로 저장한다.
    unknown_only = unknown_packages - highest_severity_by_page.keys()
    updates = {**dict.fromkeys(sorted(unknown_only), "unknown"), **highest_severity_by_page}
    summary.update(matched_count=len(matches), affected_count=len(highest_severity_by_page),
                   unknown_count=len(unknown_only), total_updates=len(updates))
    progress(stage="saving", message="분석 결과를 Notion에 저장하고 있습니다.", **summary)
    for page_id, severity in updates.items():
        notion.update_database_rows(
            page_id=page_id,
            properties={
                "vulnerability": {"select": {"name": severity}}
            },
        )
        summary["updated_count"] += 1
        progress(stage="saving", message="분석 결과를 Notion에 저장하고 있습니다.", **summary)

    affected_packages = set(highest_severity_by_page)
    send_task_message(
        "취약도 분석이 완료되었습니다.\n"
        f"분석 범위: {'저장된 전체 공지' if started_at is None and ended_at is None else f'{started_at} ~ {ended_at}'}\n"
        f"공지 {len(advisories)}건 / 검사 패키지 {len(service_packages)}개 / "
        f"취약점 일치 {len(matches)}건 / 영향 패키지 {len(affected_packages)}개 / "
        f"알 수 없음 {len(unknown_only)}개\n"
        "Notion 결과 반영을 완료했습니다.",
        task_name="취약도 분석",
    )
    return summary
