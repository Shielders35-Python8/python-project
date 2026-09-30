from notion_client import Client
from notion_client.helpers import iterate_paginated_api

from source.config.config import get_env
from source.common.slack.notifications import notify_errors


def _parse_property_value(property_value: dict):
    """노션 속성에서 비교 및 출력에 사용할 값을 추출한다."""
    property_type = property_value["type"]
    value = property_value.get(property_type)

    if property_type in ("title", "rich_text"):
        return "".join(item["plain_text"] for item in value or [])
    if property_type in ("select", "status"):
        return value["name"] if value else None
    if property_type == "multi_select":
        return [item["name"] for item in value or []]
    if property_type == "date":
        return value["start"] if value else None
    if property_type == "relation":
        return [item["id"] for item in value or []]
    if property_type == "formula":
        return _parse_property_value(value) if value else None
    if property_type == "unique_id" and value:
        prefix = value.get("prefix")
        return f"{prefix}-{value['number']}" if prefix else str(value["number"])
    return value


class NotionClient:
    @notify_errors("Notion 연결")
    def __init__(self):
        self.client = Client(auth=get_env("NOTION_TOKEN"))

    @notify_errors("Notion 데이터베이스 생성")
    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict,
        is_inline: bool = False,
    ) -> dict:
        """부모 페이지 아래에 데이터베이스와 첫 데이터 소스를 생성한다.

        Args:
            parent_page_id: 데이터베이스를 생성할 부모 노션 페이지 ID.
            title: 데이터베이스 이름.
            properties: 컬럼 스키마. SERVICE_SCHEMA, ADVISORIES_SCHEMA 또는
                build_service_package_schema의 반환값을 전달한다.
            is_inline: True이면 부모 페이지 본문에 인라인으로 표시한다.

        Returns:
            생성된 데이터베이스 응답. id는 데이터베이스 ID이며,
            data_sources[0]["id"]는 조회 및 관계 설정에 사용할 데이터 소스 ID다.
            API 오류는 호출부로 전달한다.
        """
        return self.client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": title}}],
            initial_data_source={"properties": properties},
            is_inline=is_inline,
        )

    @notify_errors("Notion 행 생성")
    def create_database_row(self, data_source_id: str, properties: dict) -> dict:
        """데이터 소스에 새 행(노션 페이지) 하나를 생성한다.

        Args:
            data_source_id: 행을 추가할 데이터 소스 ID (데이터베이스 ID와 다름).
            properties: 컬럼 이름과 값을 담은 Notion 형식의 딕셔너리.
                대상 데이터 소스의 컬럼 타입에 맞춰 전달한다.
                관계형 값에는 연결할 행의 실제 노션 페이지 ID를 사용한다.

        Returns:
            생성된 노션 페이지 응답. id는 노션이 발급한 실제 페이지 ID이며,
            이후 관계 연결과 행 업데이트에 사용한다.

        Raises:
            APIResponseError: 노션 API 요청이 실패한 경우.
        """
        return self.client.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=properties,
        )

    @notify_errors("Notion 데이터 조회")
    def get_database_rows(
        self,
        data_source_id: str,
        date_column: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> list[dict]:
        """데이터 소스의 모든 행을 조회하고 컬럼별 값을 반환한다.

        Args:
            data_source_id: 조회할 데이터 소스 ID (데이터베이스 ID와 다름).
            date_column: 날짜 조건을 적용할 날짜 속성 이름.
            started_at: 시작일 또는 시각 (ISO 8601, 경계 포함).
            ended_at: 종료일 또는 시각 (ISO 8601, 경계 포함).

        Returns:
            컬럼 이름을 키로 하는 딕셔너리 목록. 날짜는 시작 시각,
            관계는 페이지 ID 목록으로 반환한다. page_id는 직접 만든 id
            컬럼과 구분되는 실제 노션 페이지 ID이며 업데이트에 사용한다.

        Raises:
            ValueError: 날짜 조건을 전달하면서 date_column을 생략한 경우.
            APIResponseError: 노션 API 요청이 실패한 경우.
        """
        if (started_at is not None or ended_at is not None) and not date_column:
            raise ValueError("날짜 조건을 사용하려면 date_column이 필요합니다.")

        query = {"data_source_id": data_source_id, "page_size": 100}
        filters = []
        if started_at is not None:
            filters.append(
                {"property": date_column, "date": {"on_or_after": started_at}}
            )
        if ended_at is not None:
            filters.append(
                {"property": date_column, "date": {"on_or_before": ended_at}}
            )
        if filters:
            query["filter"] = filters[0] if len(filters) == 1 else {"and": filters}

        rows = []
        for page in iterate_paginated_api(self.client.data_sources.query, **query):
            row = {
                name: _parse_property_value(value)
                for name, value in page["properties"].items()
            }
            # 같은 이름의 컬럼이 있어도 업데이트에는 실제 페이지 ID를 사용한다.
            row["page_id"] = page["id"]
            rows.append(row)
        return rows

    @notify_errors("Notion 결과 저장")
    def update_database_rows(self, page_id: str, properties: dict) -> dict:
        """노션 행의 지정한 컬럼을 업데이트한다.

        Args:
            page_id: 수정할 노션 행의 실제 페이지 ID.
            properties: 변경할 컬럼과 값을 담은 Notion 형식의 딕셔너리.

        Returns:
            업데이트된 노션 페이지 응답. API 오류는 호출부로 전달한다.
        """
        return self.client.pages.update(page_id=page_id, properties=properties)
