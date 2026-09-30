# source/services/advisory_sync.py
from datetime import datetime, timedelta, timezone

from source.common.github_advisory.advisories import get_advisories
from source.common.notion.notion import NotionClient
from source.common.slack.notifications import notify_errors
from source.config.config import get_env


def _parse_datetime(value) -> datetime | None:
    """GitHub('...Z') / Notion('...+00:00', '.000') 형식의 날짜를 UTC 분 단위 datetime 으로 변환

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


def _filter_exist_advisories(
    notion: NotionClient, data_source_id: str, advisories: list[dict]
) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Notion 에 이미 있는 advisory 를 (id, published_at) 로 찾아 생성/수정 대상으로 분류

    - (id, published_at) 이 같은 행이 없으면 → 생성 대상
    - 같은 행이 있고 updated_at 도 같으면 → 제외 (이미 적재됨)
    - 같은 행이 있고 updated_at 이 다르면 → 수정 대상 (GitHub 에서 갱신된 공지)
    - id 가 없는 advisory 는 식별/적재할 수 없으므로 제외
    - Notion 조회 실패 시 예외를 그대로 전달 (중복 적재 방지)

    Return: (to_create(list(dict)), to_update(list((page_id, advisory))))
    """
    if not advisories:
        return [], []

    # 1. 비교 가능한 advisory 만 추리고, 조회 범위로 쓸 published_at 수집
    valid_advisories = []
    published_list = []
    for advisory in advisories:
        if not isinstance(advisory, dict) or not advisory.get("id"):
            print("id 없는 advisory 제외 > _filter_exist_advisories > ", advisory)
            continue
        valid_advisories.append(advisory)

        published_at = _parse_datetime(advisory.get("published_at"))
        if published_at:
            published_list.append(published_at)

    # published_at 이 하나도 없으면 Notion 조회 범위를 정할 수 없으므로 전부 생성 대상
    if not published_list:
        return valid_advisories, []

    # 2. Notion published_at 컬럼 기준으로 범위 조회
    #    경계/시간대 해석 차이로 누락되지 않도록 앞뒤 하루씩 여유를 두고, 정확한 비교는 아래에서 한다
    started_at = (min(published_list) - timedelta(days=1)).strftime("%Y-%m-%d")
    ended_at = (max(published_list) + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = notion.get_database_rows(
        data_source_id=data_source_id,
        date_column="published_at",
        started_at=started_at,
        ended_at=ended_at,
    ) or []

    # 3. Notion 에 이미 있는 (id, published_at) → 행 정보
    #    같은 키의 행이 여러 개면(기존 중복) 첫 번째 행만 사용
    exist = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        notion_id = row.get("id")
        notion_published_at = _parse_datetime(row.get("published_at"))
        page_id = row.get("page_id")
        if notion_id and notion_published_at and page_id:
            exist.setdefault((notion_id, notion_published_at), row)

    # 4. 생성 / 수정 / 제외 분류
    to_create, to_update = [], []
    for advisory in valid_advisories:
        key = (advisory.get("id"), _parse_datetime(advisory.get("published_at")))
        row = exist.get(key)
        if row is None:
            to_create.append(advisory)
            continue

        github_updated_at = _parse_datetime(advisory.get("updated_at"))
        notion_updated_at = _parse_datetime(row.get("updated_at"))
        # GitHub 쪽 updated_at 이 없으면 갱신 여부를 알 수 없으므로 제외
        if github_updated_at and github_updated_at != notion_updated_at:
            to_update.append((row["page_id"], advisory))

    skipped = len(advisories) - len(to_create) - len(to_update)
    print(f"notion 중복 필터링 : {len(advisories)} 건 중 생성 {len(to_create)} 건, 수정 {len(to_update)} 건, 제외 {skipped} 건")

    return to_create, to_update

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

    advisories = get_advisories(dates or []) or []
    to_create, to_update = _filter_exist_advisories(notion, data_source_id, advisories)
    inserted, updated, failed = 0, 0, []
    print("========================== 적재 시작 =========================")
    for advisory in to_create:
        try:
            notion.create_database_row(data_source_id, _to_notion_properties(advisory))
            inserted += 1
        except Exception as e:
            failed.append({"id": advisory.get("id"), "action": "create", "error": str(e)})

    for page_id, advisory in to_update:
        try:
            notion.update_database_rows(page_id, _to_notion_properties(advisory))
            updated += 1
        except Exception as e:
            failed.append({"id": advisory.get("id"), "action": "update", "error": str(e)})
    print("========================== 적재 완료 =========================")
    return {
        "fetched": len(advisories),
        "inserted": inserted,
        "updated": updated,
        "skipped": len(advisories) - len(to_create) - len(to_update),
        "failed": failed,
    }