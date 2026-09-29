"""GitHub 보안 공지 DB의 Notion 컬럼 정의.

ADVISORIES_SCHEMA를 데이터 소스 생성 요청의 properties에 전달한다.
한 행은 GHSA 공지 하나이며 id를 기준으로 최신 내용을 갱신한다고 가정한다.
DB 생성, 수집, 저장, JSON 직렬화는 이 파일에서 실행하지 않는다.

저장·조회 담당자의 변환 규칙:
    - id는 수집 모듈에서 ghsa_id를 바꾼 값이다. Notion 페이지 ID와 구분한다.
    - title은 공지 제목이며 Notion 행의 제목으로 사용한다.
    - published와 updated_at은 GitHub 시각, collected_at은 실제 수집 시각이다.
      날짜 값은 시간대가 있는 ISO 8601 문자열로 전달한다.
    - cve_id, severity, withdrawn_at 등 값이 없는 필드는 조회 시 None으로 복원한다.
      withdrawn_at은 GitHub가 공지를 철회한 시각이며 누락 시 철회 여부를 단정하지 않는다.
    - vulnerabilities는 GitHub 원본 배열을 JSON 문자열로 저장한다.
      package.ecosystem/name, vulnerable_version_range, first_patched_version 등
      패키지·버전 정보를 보존하고, 조회 시 json.loads로 list[dict]로 복원한다.
      미수집 값을 임의로 빈 배열로 바꾸지 않고 검토할 수 있도록 남긴다.
    - summary와 vulnerabilities의 긴 텍스트는 rich_text 항목당 2,000자 이하로
      분할해 저장하고 순서대로 이어 붙여 복원한다. 배열 길이와 요청 크기 제한도
      확인해야 하며, 제한 초과 데이터를 조용히 잘라 저장하지 않는다.

협업 가정:
    현재 source/advisories.py에는 vulnerabilities와 withdrawn_at이 빠져 있다.
    수집 담당자가 이 필드를 보존하고 collected_at을 추가한다고 가정한다.
    버전별 개별 항목으로 펼치는 작업은 조회 후 processor.py에서 수행한다.

공식 규격:
    https://developers.notion.com/reference/property-object
    https://developers.notion.com/reference/request-limits
"""


ADVISORIES_SCHEMA: dict = {
    "id": {"rich_text": {}},
    "title": {"title": {}},
    "source": {
        "select": {"options": [{"name": "github_advisory"}]}
    },
    "url": {"url": {}},
    "published": {"date": {}},
    "updated_at": {"date": {}},
    "severity": {
        "select": {
            "options": [
                {"name": "low"},
                {"name": "medium"},
                {"name": "high"},
                {"name": "critical"},
            ]
        }
    },
    "summary": {"rich_text": {}},
    "cve_id": {"rich_text": {}},
    "vulnerabilities": {"rich_text": {}},
    "withdrawn_at": {"date": {}},
    "collected_at": {"date": {}},
}
