"""서비스별 설치 패키지 DB의 Notion 컬럼 정의.

서비스 데이터 소스를 먼저 생성한 뒤, 반환된 data_source_id를
build_service_package_schema에 전달한다. 반환값은 생성 요청의 properties다.
실제 ID를 알아야 관계를 선언할 수 있어 상수 대신 스키마 반환 함수를 사용한다.
함수는 딕셔너리만 만들며 외부 호출이나 DB 생성·수정을 실행하지 않는다.

저장·조회 담당자의 변환 규칙:
    - id는 INST-001 같은 설치 항목 식별자다. Notion 페이지 ID와 구분한다.
    - service_id는 서비스 DB를 향한 단방향 관계형 속성이다.
      mock의 SVC-001을 해당 서비스의 Notion 페이지 ID로 찾아서 연결한다.
      패키지 하나당 서비스 하나만 연결하도록 저장 담당자가 검증한다.
      조회 시에는 관계 대상 페이지의 업무 id를 읽어 SVC-001로 복원한다.
    - package_name은 행의 제목이며 같은 패키지가 여러 서비스에 있어도 된다.
    - installed_version은 텍스트다. mock의 None은 빈 rich_text로 저장하고
      조회 시 None으로 복원한다. 빈 값을 '최신 버전'이나 '영향 없음'으로 보지 않는다.
    - id와 (service_id, ecosystem, package_name)의 중복 검사는 저장 담당자가 한다.

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
            "select": {"options": [{"name": "pip"}]}
        },
        "package_name": {"title": {}},
        "installed_version": {"rich_text": {}},
    }
