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

def update_notion_database(data_source_id: str):

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

    update_num = int(input("수정할 번호를 입력하세요. -> "))

    page_id = pages[update_num-1]['id']

    print("\n변경할 상태 선택")
    print("1. Active")
    print("2. inActive")
    print("-" * 30)

    status_num = input("번호 선택: ")

    if status_num == "1":
        new_status = "Active"

        print("\n변경할 상태 선택")
        print("1. medium")
        print("2. low")
        print("-" * 30)

        impact_num = input("번호 선택: ")

        if impact_num == '1':
            new_impact = "medium"
        elif impact_num == '2':
            new_impact = "low"
        else:
            print("❌ 잘못된 번호입니다.")
            exit()
        
    elif status_num == "2":
        new_status = "inActive"
        new_impact = "high"
    else:
        print("❌ 잘못된 번호입니다.")
        exit()


    # # ..............................................
    # # 8. 상태값만 수정
    notion.pages.update(
        page_id=page_id,
        properties={
            "상태" : {
                "select" : { "name" : new_status }
            },
            "영향도" : {
                "select" : { "name" : new_impact }
            }
        }
    )

    print(f"\n✅ 상태가 '{new_status}' / 영향도가 '{new_impact}'(으)로 수정되었습니다.")

if __name__ == "__main__":
    update_notion_database(os.getenv("DATA_SOURCE_ID_AUTO"))