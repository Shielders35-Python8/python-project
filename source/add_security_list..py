import os
from dotenv import load_dotenv, set_key, find_dotenv
from notion_client import Client

# .env 파일 로드
load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

if NOTION_TOKEN is None or NOTION_DB_ID is None:
    raise RuntimeError(
        "NOTION_TOKEN 또는 NOTION_DB_ID 설정되어 있지 않습니다."
    )

# Notion 클라이언트
notion = Client(auth=NOTION_TOKEN)

def add_notion_database(data_source_id: str):

    records = [
        {
            "보안 목록": {
                "title": [
                    {"text": {"content": "Buffer Overflow"}}
                ]
            },
            "상태": {
                "select": {"name": "Active"}
            },
            "영향도": {
                "select": {"name": "low"}
            },
        },
        {
            "보안 목록": {
                "title": [
                    {"text": {"content": "Type Confusion"}}
                ]
            },
            "상태": {
                "select": {"name": "inActive"}
            },
            "영향도": {
                "select": {"name": "high"}
            },
        },  
    ]

    # 2개의 레코드를 차례대로 추가
    for record in records:

        new_page = notion.pages.create(
            parent={
                "data_source_id": data_source_id
            },
            properties=record
        )

        print("새 Row 추가:", new_page["id"])

if __name__ == "__main__":
    add_notion_database(os.getenv("DATA_SOURCE_ID_AUTO"))
