# source/services/advisory_sync.py
from datetime import datetime, timezone
from functools import partial

from notion_client.helpers import iterate_paginated_api

from source.common.github_advisory.advisories import get_advisories
from source.common.notion.notion import NotionClient
from source.common.slack.notifications import notify_errors
from source.common.slack.slack import send_task_message
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


def _query_rows_by_ids(notion: NotionClient, data_source_id: str, ids: list[str]) -> list[dict]:
    """Notion advisories 데이터 소스에서 id 컬럼이 ids 중 하나와 같은 행만 조회

    notion.py 의 get_database_rows 는 날짜 조건만 지원하므로, 같은 클라이언트와 요청 정책(query_policy)을
    그대로 사용해 id 조건으로 직접 조회한다.

    Return: list({"id", "published_at", "updated_at", "page_id"})
    """
    def text(prop):
        return "".join(item.get("plain_text", "") for item in (prop or {}).get("rich_text") or [])

    def date(prop):
        value = (prop or {}).get("date")
        return value.get("start") if isinstance(value, dict) else None

    query_page = notion.client.data_sources.query
    if getattr(notion, "query_policy", None) is not None:
        query_page = partial(notion.query_policy.call, query_page)

    rows = []
    # Notion compound filter 조건 개수 제한을 고려해 100 개씩 나누어 조회
    for i in range(0, len(ids), 100):
        id_filter = {"or": [{"property": "id", "rich_text": {"equals": ghsa_id}} for ghsa_id in ids[i:i + 100]]}
        for page in iterate_paginated_api(query_page, data_source_id=data_source_id, filter=id_filter, page_size=100):
            properties = page.get("properties") or {}
            rows.append({
                "id": text(properties.get("id")),
                "published_at": date(properties.get("published_at")),
                "updated_at": date(properties.get("updated_at")),
                "page_id": page.get("id"),
            })
    return rows


def _filter_exist_advisories(
    notion: NotionClient, data_source_id: str, advisories: list[dict]
) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Notion 에 이미 있는 advisory 를 id 로 찾아 생성/수정 대상으로 분류

    - id 가 같은 행이 없으면 → 생성 대상
    - id 가 같은 행이 있고 published_at, updated_at 도 같으면 → 제외 (이미 적재됨)
    - id 가 같은 행이 있고 published_at 이나 updated_at 이 다르거나 비어 있으면 → 기존 행 수정
    - id 가 같은 행이 여러 개면(기존 중복) 하나만 남기고 나머지는 삭제. 남길 행 우선순위:
        1. published_at, updated_at 이 GitHub 과 모두 같은 행
        2. published_at, updated_at 이 모두 채워진 행
        3. 그 외 (조회 순서상 첫 행)
      삭제 순서: published_at/updated_at 이 비어 있거나 다른 행 → id/published_at/updated_at 이 모두 같은 행
    - id 가 없는 advisory 는 식별/적재할 수 없으므로 제외
    - Notion 조회 실패 시 예외를 그대로 전달 (중복 적재 방지)

    Return: (to_create(list(dict)), to_update(list((page_id, advisory))))
    """
    if not advisories:
        return [], []

    # 1. 비교 가능한 advisory 만 추림 (같은 id 가 여러 번 오면 첫 번째만 사용)
    valid_advisories = {}
    for advisory in advisories:
        if not isinstance(advisory, dict) or not advisory.get("id"):
            print("id 없는 advisory 제외 > _filter_exist_advisories > ", advisory)
            continue
        valid_advisories.setdefault(advisory["id"], advisory)

    if not valid_advisories:
        return [], []

    # 2. Notion 에서 이번 수집 결과의 id 와 같은 행만 조회
    rows = _query_rows_by_ids(notion, data_source_id, list(valid_advisories))
    rows_by_id = {}
    for row in rows:
        if row.get("id") in valid_advisories and row.get("page_id"):
            rows_by_id.setdefault(row["id"], []).append(row)

    def is_same(row, advisory):
        """published_at, updated_at 이 모두 GitHub 값과 같은지 (비어 있으면 다름)"""
        row_published = _parse_datetime(row.get("published_at"))
        row_updated = _parse_datetime(row.get("updated_at"))
        return (
            row_published is not None and row_updated is not None
            and row_published == _parse_datetime(advisory.get("published_at"))
            and row_updated == _parse_datetime(advisory.get("updated_at"))
        )

    def keep_rank(row, advisory):
        """남길 행 우선순위 (작을수록 우선)"""
        if is_same(row, advisory):
            return 0
        if _parse_datetime(row.get("published_at")) and _parse_datetime(row.get("updated_at")):
            return 1
        return 2

    # 3. id 별로 남길 행 하나를 고르고, 나머지는 삭제 대상
    keep = {}
    duplicate_rows = []
    for ghsa_id, id_rows in rows_by_id.items():
        advisory = valid_advisories[ghsa_id]
        # sorted 는 안정 정렬이라 같은 우선순위면 조회 순서상 첫 행이 남는다
        ordered = sorted(id_rows, key=lambda row: keep_rank(row, advisory))
        keep[ghsa_id] = ordered[0]
        duplicate_rows.extend((row, advisory) for row in ordered[1:])

    # 4. 기존 중복 행 삭제 (Notion 휴지통으로 이동), 실패해도 분류/적재는 계속 진행
    #    비어 있거나 다른 행을 먼저, 값이 모두 같은 행을 나중에 삭제
    duplicate_rows.sort(key=lambda item: is_same(*item))
    deleted = 0
    for row, _ in duplicate_rows:
        try:
            notion.delete_database_row(row["page_id"])
            deleted += 1
        except Exception as e:
            print(f"notion 중복 행 삭제 실패 > _filter_exist_advisories > {row.get('id')} ({row['page_id']}) > ", e)

    # 5. 생성 / 수정 / 제외 분류
    to_create, to_update = [], []
    for ghsa_id, advisory in valid_advisories.items():
        row = keep.get(ghsa_id)
        if row is None:
            to_create.append(advisory)
        elif not is_same(row, advisory):
            to_update.append((row["page_id"], advisory))

    skipped = len(advisories) - len(to_create) - len(to_update)
    print(f"notion 중복 필터링 : {len(advisories)} 건 중 생성 {len(to_create)} 건, 수정 {len(to_update)} 건, 제외 {skipped} 건"
          f" / 기존 중복 행 삭제 {deleted} 건 (실패 {len(duplicate_rows) - deleted} 건)")

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


def _send_sync_summary(summary: dict, dates=None) -> None:
    """적재 결과 요약을 Slack 으로 전송, 전송 실패는 적재 결과에 영향을 주지 않음"""
    try:
        failed = summary.get("failed") or []
        if summary.get("error"):
            message = (
                "GitHub 보안 공지 Notion 적재가 중간에 중단되었습니다.\n"
                f"중단 단계 : {summary.get('stage')} / 원인 : {str(summary.get('error'))[:200]}\n"
                "아래는 중단 전까지 Notion 에 반영된 건수입니다. (Notion 은 롤백되지 않음)\n"
            )
        else:
            message = "GitHub 보안 공지 Notion 적재가 완료되었습니다.\n"
        if dates:
            message += f"기간 : {' ~ '.join(str(date) for date in dates)}\n"
        message += (
            f"수집 {summary.get('fetched', 0)}건 / 생성 {summary.get('inserted', 0)}건 / "
            f"수정 {summary.get('updated', 0)}건 / 제외 {summary.get('skipped', 0)}건 / 실패 {len(failed)}건"
        )
        # 실패 건은 최대 5건까지만 표시 (메시지가 너무 길어지지 않도록)
        for item in failed[:5]:
            message += f"\n- {item.get('id')} ({item.get('action')}): {str(item.get('error'))[:100]}"
        if len(failed) > 5:
            message += f"\n... 외 {len(failed) - 5}건"

        send_task_message(message, task_name="보안 공지 Notion 적재")
    except Exception as e:
        print("slack summary send error > _send_sync_summary > ", e)


@notify_errors("보안 공지 Notion 적재")
def sync_advisories_to_notion(dates=None, *, progress=None, query_policy=None) -> dict:
    """GitHub advisories 를 조회해 Notion advisories DB 에 적재하고 결과 요약을 리턴

    Args:
        dates(list(str)): published 날짜 조건 (0~2개)
        progress(callable): 진행 상황을 전달받는 콜백 (웹 진행 상태 표시용), 없으면 무시
        query_policy(NotionQueryPolicy): Notion 요청 간격/재시도 정책, 없으면 기본 클라이언트 사용
    """
    data_source_id = get_env("NOTION_ADVISORIES_DATA_SOURCE_ID")
    if not data_source_id or not data_source_id.strip():
        raise ValueError("Notion 공지 데이터 소스 ID가 필요합니다.")
    progress = progress or (lambda **values: None)
    options = {"timeout_ms": 15_000, "query_policy": query_policy} if query_policy else {}
    notion = NotionClient(**options)
    try:
        progress(stage="fetching", message="GitHub 공지를 가져오고 있습니다.")
        advisories = get_advisories(dates or [], raise_on_error=True) or []
        fetched = len(advisories)

        progress(stage="deduplicating", message="Notion에 저장된 공지와 중복을 확인하고 있습니다.", fetched=fetched)
        to_create, to_update = _filter_exist_advisories(notion, data_source_id, advisories)
        skipped = fetched - len(to_create) - len(to_update)

        inserted, updated, failed = 0, 0, []
        progress(stage="saving", message="공지를 Notion에 저장하고 있습니다.",
                 skipped=skipped, total=len(to_create) + len(to_update))
        print("========================== 적재 시작 =========================")

        for advisory in to_create:

            try:
                notion.create_database_row(data_source_id, _to_notion_properties(advisory))
                inserted += 1
            except Exception as e:
                failed.append({"id": advisory.get("id"), "action": "create", "error": str(e)})
            progress(inserted=inserted, updated=updated, failed_count=len(failed))

        for page_id, advisory in to_update:
            try:
                notion.update_database_rows(page_id, _to_notion_properties(advisory))
                updated += 1
            except Exception as e:
                failed.append({"id": advisory.get("id"), "action": "update", "error": str(e)})
            progress(inserted=inserted, updated=updated, failed_count=len(failed))
        print("========================== 적재 완료 =========================")

        summary = {
            "fetched": fetched,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }
        _send_sync_summary(summary, dates)
        return summary
    finally:
        # 이 함수에서 만든 클라이언트만 닫는다 (다른 모듈은 각자 NotionClient 를 생성)
        notion.client.close()