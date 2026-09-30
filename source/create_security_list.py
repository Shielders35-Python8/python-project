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

# set_key로 값을 저장할 .env 파일 경로
DOTENV_PATH = find_dotenv()
print(DOTENV_PATH)

# Notion 클라이언트
notion = Client(auth=NOTION_TOKEN)


def create_notion_database():

    # 데이터베이스 제목
    title = [
        {
            "type": "text",
            "text": {
                "content": "Shielders35-Python8-DB"
            }
        }
    ]

    # 컬럼 정의
    properties = {
        "보안 목록": {
            "title": {}
        },

        "상태": {
            "select": {
                "options": [
                    {"name": "Active", "color": "green"},
                    {"name": "inActive", "color": "red"}
                ]
            }
        },

        "영향도": {
            "select": {
                "options": [
                    {"name": "high", "color": "red"},
                    {"name": "medium", "color": "orange"},
                    {"name": "low", "color": "green"},
                ]
            }
        }
    }

    # DB 생성
    db = notion.databases.create(
        parent={
            "type": "page_id",
            "page_id": NOTION_DB_ID,
        },

        title=title,

        initial_data_source={
            "properties": properties
        },
    )

    database_id = db["id"]

    print("새 데이터베이스 생성 완료!")
    print("Database ID:", database_id)

    # 생성된 DB에서 Data Source ID 가져오기
    db_info = notion.databases.retrieve(database_id)

    data_source_id = db_info["data_sources"][0]["id"]

    print("Data Source ID:", data_source_id)

    # 실제 Property 확인
    ds_info = notion.data_sources.retrieve(data_source_id)

    print("\n실제 Property:")

    for name, prop in ds_info["properties"].items():
        print(name, "->", prop["type"])

    return data_source_id

if __name__ == "__main__":
    create_notion_database()

    data_source_id = os.getenv("DATA_SOURCE_ID_AUTO")

    # # 없으면 자동 추가
    if data_source_id is None:
        data_source_id = create_notion_database()
        set_key(DOTENV_PATH, "DATA_SOURCE_ID_AUTO", data_source_id, quote_mode="never")

        os.environ["DATA_SOURCE_ID_AUTO"] = data_source_id