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
        list[dict]: db 데이터
    """
    # TODO: 내부 조회 로직 구현 예정
    return []


def update_database_rows():
    """특정 테이블의 칼럼을 업데이트 하는 함수"""
    # TODO: 내부 업데이트 로직 구현 예정
    return []
