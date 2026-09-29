"""회사에서 운영하는 MSA 서비스 DB의 Notion 컬럼 정의.

SERVICE_SCHEMA를 데이터 소스 생성 요청의 properties에 전달한다.
이 파일은 구조만 선언하며 DB 생성이나 데이터 저장을 실행하지 않는다.

저장·조회 담당자의 변환 규칙:
    - id는 SVC-001 같은 업무 식별자다. Notion 페이지 ID와 구분하고,
      중복 검사는 저장 담당자가 수행한다.
    - resource_name이 Notion에서 각 행을 표시하는 제목이다.
    - internet_exposed는 Python의 True/False/None을 각각
      Notion 선택 값 Yes/No/Unknown으로 변환한다. 조회 시 원래 값으로 복원한다.
    - 그 외 컬럼명은 company_resources_mock.json과 동일하다.

공식 속성 규격: https://developers.notion.com/reference/property-object
"""


SERVICE_SCHEMA: dict = {
    "id": {"rich_text": {}},
    "resource_name": {"title": {}},
    "business_domain": {"rich_text": {}},
    "description": {"rich_text": {}},
    "owner_team": {"rich_text": {}},
    "environment": {
        "select": {
            "options": [
                {"name": "Production"},
                {"name": "Staging"},
                {"name": "Development"},
            ]
        }
    },
    "os": {
        "select": {
            "options": [
                {"name": "Linux"},
                {"name": "Windows"},
                {"name": "Unknown"},
            ]
        }
    },
    "deployment_platform": {
        "select": {"options": [{"name": "Kubernetes"}]}
    },
    "workload_type": {
        "select": {
            "options": [
                {"name": "Web"},
                {"name": "Worker"},
                {"name": "Batch"},
            ]
        }
    },
    "business_importance": {
        "select": {
            "options": [
                {"name": "High"},
                {"name": "Medium"},
                {"name": "Low"},
            ]
        }
    },
    "internet_exposed": {
        "select": {
            "options": [
                {"name": "Yes"},
                {"name": "No"},
                {"name": "Unknown"},
            ]
        }
    },
    "service_status": {
        "select": {
            "options": [
                {"name": "Active"},
                {"name": "Inactive"},
            ]
        }
    },
}
