# source/services/advisory_sync.py
from datetime import datetime, timedelta, timezone

from source.common.github_advisory.advisories import get_advisories
from source.common.notion.notion import NotionClient
from source.common.slack.notifications import notify_errors
from source.config.config import get_env


def _parse_updated_at(value) -> datetime | None:
    """GitHub('...Z') / Notion('...+00:00', '.000') 형식의 updated_at 을 UTC 분 단위 datetime 으로 변환

    Notion 날짜 컬럼은 초 단위가 저장되지 않을 수 있어 분 단위까지만 비교한다.
    변환할 수 없는 값이면 None 을 리턴한다.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _filter_exist_advisories(notion: NotionClient, data_source_id: str, advisories: list[dict]) -> list[dict]:
    """Notion 에 id 와 updated_at 이 모두 같은 행이 이미 있으면 제외

    - id 가 없는 advisory 는 식별/적재할 수 없으므로 제외
    - updated_at 이 다르면 GitHub 에서 갱신된 공지이므로 제외하지 않음
    - Notion 조회 실패 시 예외를 그대로 전달 (중복 적재 방지)
    """
    if not advisories:
        return []

    # 1. 비교 가능한 advisory 만 추리고, 조회 범위로 쓸 updated_at 수집
    valid_advisories = []
    updated_list = []
    for advisory in advisories:
        if not isinstance(advisory, dict) or not advisory.get("id"):
            print("id 없는 advisory 제외 > _filter_exist_advisories > ", advisory)
            continue
        valid_advisories.append(advisory)

        updated_at = _parse_updated_at(advisory.get("updated_at"))
        if updated_at:
            updated_list.append(updated_at)

    # updated_at 이 하나도 없으면 비교 기준이 없으므로 그대로 리턴
    if not updated_list:
        return valid_advisories

    # 2. Notion updated_at 컬럼 기준으로 범위 조회
    #    경계/시간대 해석 차이로 누락되지 않도록 앞뒤 하루씩 여유를 두고, 정확한 비교는 아래에서 한다
    started_at = (min(updated_list) - timedelta(days=1)).strftime("%Y-%m-%d")
    ended_at = (max(updated_list) + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = notion.get_database_rows(
        data_source_id=data_source_id,
        date_column="updated_at",
        started_at=started_at,
        ended_at=ended_at,
    ) or []

    # 3. Notion 에 이미 있는 (id, updated_at) 조합
    exist = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        notion_id = row.get("id")
        notion_updated_at = _parse_updated_at(row.get("updated_at"))
        if notion_id and notion_updated_at:
            exist.add((notion_id, notion_updated_at))

    # 4. id 와 updated_at 이 모두 같은 advisory 제외
    filtered_advisories = [
        advisory for advisory in valid_advisories
        if (advisory.get("id"), _parse_updated_at(advisory.get("updated_at"))) not in exist
    ]
    print(f"notion 중복 필터링 : {len(advisories)} 건 중 {len(advisories) - len(filtered_advisories)} 건 제외")

    return filtered_advisories

def _to_notion_properties(advisory: dict) -> dict:
    """advisories flat dict → ADVISORIES_SCHEMA 형식"""
    def text(value):
        return {"rich_text": [{"text": {"content": value}}] if value else []}
    def select(value):
        return {"select": {"name": value} if value else None}
    def date(value):
        return {"date": {"start": value} if value else None}

    return {
        "id": text(advisory["id"]),
        "title": {"title": [{"text": {"content": advisory["title"] or advisory["id"]}}]},
        "url": {"url": advisory.get("url")},
        "published_at": date(advisory.get("published_at")),
        "updated_at": date(advisory.get("updated_at")),
        "severity": select(advisory.get("severity")),
        "cve_id": text(advisory.get("cve_id")),
        "ecosystem": select(advisory.get("ecosystem")),
        "package_name": text(advisory.get("package_name")),
        "package_version_range": text(advisory.get("package_version_range")),
        "reason": text(advisory.get("reason")),
    }


@notify_errors("보안 공지 Notion 적재")
def sync_advisories_to_notion(dates=None) -> dict:
    """GitHub advisories 를 조회해 Notion advisories DB 에 적재하고 결과 요약을 리턴"""
    notion = NotionClient()
    data_source_id = get_env("NOTION_ADVISORIES_DATA_SOURCE_ID")

    advisories = get_advisories(dates or [])
    advisories = _filter_exist_advisories(notion, data_source_id, advisories)
    inserted, failed = 0, []
    print("========================== 적재 시작 =========================")
    for advisory in advisories:
        try:
            notion.create_database_row(data_source_id, _to_notion_properties(advisory))
            inserted += 1
        except Exception as e:
            failed.append({"id": advisory.get("id"), "error": str(e)})
    print("========================== 적재 완료 =========================")
    return {"fetched": len(advisories), "inserted": inserted, "failed": failed}