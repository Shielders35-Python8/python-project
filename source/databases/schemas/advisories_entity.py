"""GitHub 보안 공지 DB의 Notion 컬럼 정의.

ADVISORIES_SCHEMA를 데이터 소스 생성 요청의 properties에 전달한다.
한 행은 GHSA 공지의 패키지·취약 버전 범위 하나를 나타낸다.
DB 생성, 수집, 저장, JSON 직렬화는 이 파일에서 실행하지 않는다.

공식 규격:
    https://developers.notion.com/reference/property-object
    https://developers.notion.com/reference/request-limits
"""

ADVISORIES_SCHEMA: dict = {
    "id": {"rich_text": {}},
    "title": {"title": {}},
    "url": {"url": {}},
    "published_at": {"date": {}},
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
    "cve_id": {"rich_text": {}},
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
    "package_name": {"rich_text": {}},
    "package_version_range": {"rich_text": {}},
    "reason": {"rich_text": {}},
}
