import re

from source.common.notion.notion import NotionClient
from source.config.config import get_env
from source.common.slack.notifications import notify_errors
from source.common.slack.slack import send_task_message


@notify_errors("취약도 분석")
def evaluate_impact(started_at, ended_at):
    """노션 db에서 가져온 service-package테이블의 데이터와 advisories테이블의 데이터를 비교한다
    각 advisories 마다 "package_name", "package_version_range", "ecosystem" 과 service_package의 "package_name", "package_version", "ecosystem"을 비교하고
    일치하는 경우, 해당 service_package의 'vulnerability' 컬럼을 'severity'컬럼의 값으로 업데이트 한다.
    """
    notion = NotionClient()

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

    # 3. advisories와 service_packages의 칼럼을 비교해서 일치하는 경우를 찾는다. 3칼럼 모두 같아야함. package_version과
    # package_version_range는 범위 비교 필요.
    def version_matches_range(version, version_range):
        """숫자 버전과 쉼표로 연결된 비교 조건(AND)만 처리한다. 현재 단계에서 문자 포함 처리여부는 고려x"""
        if not isinstance(version, str) or not isinstance(version_range, str):
            return False
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version.strip()) is None:
            return False

        installed = tuple(map(int, version.strip().split(".")))
        for condition in version_range.split(","):
            match = re.fullmatch(
                r"\s*(<=|>=|==|!=|<|>|=)?\s*([0-9]+(?:\.[0-9]+)*)\s*",
                condition,
            )
            if match is None:
                return False

            operator, boundary = match.groups()
            limit = tuple(map(int, boundary.split(".")))
            length = max(len(installed), len(limit))
            # 1.2와 1.2.0을 같은 버전으로 비교한다.
            current = installed + (0,) * (length - len(installed))
            limit += (0,) * (length - len(limit))
            comparisons = {
                "<": current < limit,
                "<=": current <= limit,
                ">": current > limit,
                ">=": current >= limit,
                "=": current == limit,
                "==": current == limit,
                "!=": current != limit,
            }
            if not comparisons[operator or "=="]:
                return False
        return True

    matches = []
    for advisory in advisories:
        if not advisory.get("package_name") or not advisory.get("ecosystem"):
            continue
        for service_package in service_packages:
            if advisory["package_name"] != service_package.get(
                "package_name"
            ) or advisory["ecosystem"] != service_package.get("ecosystem"):
                continue
            if version_matches_range(
                service_package.get("package_version"),
                advisory.get("package_version_range"),
            ):
                matches.append(
                    {"advisory": advisory, "service_package": service_package}
                )

    # 4. 일치하는 경우에 해당하는 service_package의 'vulnerability' 컬럼을 'severity'컬럼의 값으로 업데이트 한다.
    # common\notion\notion.py의 def update_database_rows()를 사용한다.
    for match in matches:
        notion.update_database_rows(
            page_id=match["service_package"]["page_id"],
            properties={
                "vulnerability": {"select": {"name": match["advisory"]["severity"]}}
            },
        )

    affected_packages = {match["service_package"]["page_id"] for match in matches}
    send_task_message(
        "취약도 분석이 완료되었습니다.\n"
        f"분석 기간: {started_at} ~ {ended_at}\n"
        f"공지 {len(advisories)}건 / 검사 패키지 {len(service_packages)}개 / "
        f"취약점 일치 {len(matches)}건 / 영향 패키지 {len(affected_packages)}개\n"
        "Notion 결과 반영을 완료했습니다.",
        task_name="취약도 분석",
    )
