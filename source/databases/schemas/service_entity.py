"""회사에서 운영하는 MSA 서비스 DB의 Notion 컬럼 정의.

SERVICE_SCHEMA를 데이터 소스 생성 요청의 properties에 전달한다.
이 파일은 구조만 선언하며 DB 생성이나 데이터 저장을 실행하지 않는다.

공식 속성 규격: https://developers.notion.com/reference/property-object
"""

SERVICE_SCHEMA: dict = {
    "id": {"rich_text": {}},
    "resource_name": {"title": {}},
    "business_domain": {"rich_text": {}},
    "description": {"rich_text": {}},
    "business_importance": {
        "select": {
            "options": [
                {"name": "High"},
                {"name": "Medium"},
                {"name": "Low"},
            ]
        }
    },
}
