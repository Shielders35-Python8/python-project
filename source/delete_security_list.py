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

notion = Client(auth=NOTION_TOKEN)

def delete_notion_database(data_source_id: str):

    result = notion.data_sources.query(
        data_source_id=data_source_id
    )

    pages = result["results"]

    print("\n=== 보안 목록 ===")

    for i, page in enumerate(pages, start=1):

        properties = page["properties"]

        security_list = properties["보안 목록"]["title"][0]["plain_text"]
        security_status = properties["상태"]["select"]["name"]

        security_impact = properties["영향도"]["select"]["name"]

        print(f"{i}. 보안 목록: {security_list}")
        print(f"   상태: {security_status}")
        print(f"   영향도: {security_impact}")
        print("-" * 30)

    delete_num = int(input("삭제할 번호를 입력하세요. -> ")) 

    if delete_num <= len(pages):
        page_id = pages[delete_num-1]['id']
    else:
        print("❌ 잘못된 번호입니다.")
        exit()

    page_id = pages[delete_num-1]['id']

    notion.pages.update(page_id=page_id, archived=True)
    print(f"\n✅ {delete_num}번 항목을 삭제했습니다.")
if __name__ == "__main__":
    delete_notion_database(os.getenv("DATA_SOURCE_ID_AUTO"))