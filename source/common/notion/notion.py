from notion_client import Client

from source.config.config import get_env


NOTION_TOKEN = get_env("NOTION_TOKEN")
notion = Client(auth=NOTION_TOKEN)


def get_database_rows(
    data_source_id: str,
    date_column: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> list[dict]:
    """특정 db의 데이터를 필터값에 의해 가져오는 함수
    Args:
        data_source_id (str): db id
        date_column (str): 날짜 필드명
        start_at (str): 시작일
        end_at (str): 종료일
    Returns:
        list[dict]: db 데이터. 각 행에 노션 응답의 최상위 id를 page_id 키로
        함께 반환해야 한다. 직접 만든 id 컬럼 값과 구분하며,
        processor.py에서 해당 노션 행을 업데이트할 때 사용한다.
    """
    # TODO: 내부 조회 로직 구현 예정
    return []


def update_database_rows(page_id: str, properties: dict) -> dict:
    """노션 행의 지정한 컬럼을 업데이트한다.

    Args:
        page_id: 수정할 노션 행의 실제 페이지 ID.
        properties: 변경할 컬럼과 값을 담은 Notion 형식의 딕셔너리.

    Returns:
        dict: 업데이트된 노션 페이지 응답.
    """
    # TODO: 내부 업데이트 로직은 구현 예정
    ...
