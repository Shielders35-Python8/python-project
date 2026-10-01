# source/services/advisory_sync.py
from datetime import datetime, timedelta, timezone

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


def _filter_exist_advisories(
    notion: NotionClient, data_source_id: str, advisories: list[dict]
) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Notion 에 이미 있는 advisory 를 id 를 키로 찾아 생성/수정 대상으로 분류
    - published_at 은 수정되지 않는 값으로, 필터링 조건을 줄이기 위해 조회 조건으로 추가

    - id 가 같은 행이 없으면 → 생성 대상
    - 같은 행이 있고 updated_at 도 같으면 → 제외 (이미 적재됨)
    - 같은 행이 있고 updated_at 이 다르면 → 수정 대상 (GitHub 에서 갱신된 공지)
    - id 가 없는 advisory 는 식별/적재할 수 없으므로 제외
    - Notion 조회 실패 시 예외를 그대로 전달 (중복 적재 방지)
    - 같은 키의 행이 여러 개면(기존 중복) 하나의 행만 사용하고 나머지 행은 삭제

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
    #    published_at 이 빈 행은 위 범위 조회에서 이미 빠지고, id 가 빈 행은 여기서 제외
    #    Notion DB는 RDBMS와 달리 id 기반의 효율적인 대량 조회 및 고유성 제약에 한계가 있고, 
    #    전체 조회 시 API 호출 비용과 처리 시간이 증가함
    #    따라서 짧은 프로젝트 기간과 운영 부하를 고려하여 
    #    일반적으로 변경되지 않는 published_at을 보조 조회 조건으로 사용해 조회 범위를 제한 
    #    향후 저장소를 RDBMS로 전환할 경우 id에 인덱스 및 UNIQUE 제약을 적용하고 published_at 조건은 제거할 수 있다.
    #    이번 조회 대상 키만 다루며, 같은 키의 행이 여러 개면 첫 번째 행만 사용하고 나머지는 삭제 대상
    target_keys = {
        (advisory["id"], _parse_datetime(advisory.get("published_at")))
        for advisory in valid_advisories
    }
    exist = {}
    duplicate_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        notion_id = row.get("id")
        notion_published_at = _parse_datetime(row.get("published_at"))
        page_id = row.get("page_id")
        if not notion_id or not notion_published_at or not page_id:
            continue

        key = (notion_id, notion_published_at)
        if key not in target_keys:
            continue
        if key in exist:
            duplicate_rows.append((notion_id, page_id))
        else:
            exist[key] = row

    # 4. 기존 중복 행 삭제 (Notion 휴지통으로 이동), 실패해도 분류/적재는 계속 진행
    deleted = 0
    for notion_id, page_id in duplicate_rows:
        try:
            notion.delete_database_row(page_id)
            deleted += 1
        except Exception as e:
            print(f"notion 중복 행 삭제 실패 > _filter_exist_advisories > {notion_id} ({page_id}) > ", e)

    # 5. 생성 / 수정 / 제외 분류
    to_create, to_update = [], []
    for advisory in valid_advisories:
        key = (advisory["id"], _parse_datetime(advisory.get("published_at")))
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