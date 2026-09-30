"""서비스별 설치 패키지 DB의 Notion 컬럼 정의.

서비스 데이터 소스를 먼저 생성한 뒤, 반환된 data_source_id를
build_service_package_schema에 전달한다. 반환값은 생성 요청의 properties다.
실제 ID를 알아야 관계를 선언할 수 있어 상수 대신 스키마 반환 함수를 사용한다.
함수는 딕셔너리만 만들며 외부 호출이나 DB 생성·수정을 실행하지 않는다.

공식 관계형 규격: https://developers.notion.com/reference/property-object#relation
"""


def build_service_package_schema(service_data_source_id: str) -> dict:
    """연결할 서비스 데이터 소스의 실제 ID를 받아 컬럼 구조를 반환한다.

    service_data_source_id는 Notion 데이터 소스 ID이며, 부모 database_id나
    서비스의 업무 id(SVC-001), 개별 서비스 페이지 ID와는 다르다.
    호출할 때마다 새 딕셔너리를 반환하므로 다른 호출의 스키마를 변경하지 않는다.
    """
    return {
        "id": {"rich_text": {}},
        "service_id": {
            "relation": {
                "data_source_id": service_data_source_id,
                "type": "single_property",
                "single_property": {},
            }
        },
        "ecosystem": {
            "select": {
                "options": [
                    {"name": "rubygems"},
                    {"name": "npm"},
                    {"name": "pip"},
                    {"name": "maven"},
                    {"name": "nuget"},
                    {"name": "composer"},
                    {"name": "go"},
                    {"name": "rust"},
                    {"name": "erlang"},
                    {"name": "actions"},
                    {"name": "pub"},
                    {"name": "other"},
                    {"name": "swift"},
                ]
            }
        },
        "package_name": {"title": {}},
        "package_version": {"rich_text": {}},
        # 기본값은 행 생성 시 {"select": {"name": "safe"}}로 지정한다.
        "vulnerability": {
            "select": {
                "options": [
                    {"name": "safe"},
                    {"name": "low"},
                    {"name": "medium"},
                    {"name": "high"},
                    {"name": "critical"},
                ]
            }
        },
    }
