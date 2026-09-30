"""기존 Notion 함수로 서비스 패키지 mock을 목표 행 수까지 추가한다.

조회만: python -m source.example.seed_service_packages --target 500
실행:   python -m source.example.seed_service_packages --target 500 --apply

mock의 서비스 UUID는 업무 id(SVC-...)로 실제 Notion 페이지에 매핑한다.
기존 행은 수정하지 않으며, 중단 후 재실행하면 없는 행만 추가한다.
service_package_mock.json의 PKG-019~500은 기존 18개 패키지의 patch
버전을 증가시킨 합성 테스트 데이터이며, 실제 배포 버전 목록이 아니다.
"""

import argparse
import json
import time
from pathlib import Path
from uuid import UUID


MOCK_DIR = Path(__file__).resolve().parent


def package_key(row):
    return (
        tuple(sorted(str(UUID(value)) for value in row["service_id"])),
        row["ecosystem"], row["package_name"], row["package_version"],
    )


def build_plan(packages, mock_services, services, existing, target):
    """외부 요청 없이 중복·서비스 연결을 검증하고 추가할 행을 결정한다."""
    if target < 0:
        raise ValueError("target must be non-negative")
    if len(existing) >= target:
        return []

    service_pages = {}
    for service in services:
        if service["id"] in service_pages:
            raise ValueError(f"Duplicate service id: {service['id']}")
        service_pages[service["id"]] = service["page_id"]
    relation_map = {
        service["page_id"]: service_pages[service["id"]]
        for service in mock_services
    }
    by_id = {}
    keys = set()
    for row in existing:
        if row["id"] in by_id:
            raise ValueError(f"Duplicate package id: {row['id']}")
        by_id[row["id"]] = package_key(row)
        keys.add(package_key(row))

    planned = []
    for package in packages:
        row = {**package, "service_id": [
            relation_map[page_id] for page_id in package["service_id"]
        ]}
        if not row["service_id"]:
            raise ValueError(f"Missing service relation: {row['id']}")
        key = package_key(row)
        if row["id"] in by_id:
            if by_id[row["id"]] != key:
                raise ValueError(f"Conflicting package id: {row['id']}")
            continue
        if key in keys:
            continue
        planned.append(row)
        by_id[row["id"]] = key
        keys.add(key)
        if len(existing) + len(planned) == target:
            return planned
    raise ValueError(f"Not enough unique mock rows to reach {target}")


def row_properties(row):
    properties = {
        field: {"rich_text": [{"text": {"content": row[field]}}]}
        for field in ("id", "package_version")
    }
    properties.update({
        "package_name": {"title": [{"text": {"content": row["package_name"]}}]},
        "service_id": {"relation": [{"id": value} for value in row["service_id"]]},
        "ecosystem": {"select": {"name": row["ecosystem"]}},
        "vulnerability": {"select": {"name": row["vulnerability"]}},
    })
    return properties


def verify_result(before, after, planned):
    if len(after) != len(before) + len(planned):
        raise RuntimeError("Unexpected final row count; inspect Notion before rerunning")
    actual = {row["id"]: row for row in after}
    if len(actual) != len(after):
        raise RuntimeError("Duplicate package ids in Notion")
    for row in before:
        if actual.get(row["id"]) != row:
            raise RuntimeError(f"Existing row changed: {row['id']}")
    for row in planned:
        saved = actual.get(row["id"])
        if (saved is None or package_key(saved) != package_key(row)
                or saved["vulnerability"] != row["vulnerability"]):
            raise RuntimeError(f"Saved row does not match mock: {row['id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # 계획 로직을 import하거나 테스트할 때는 인증 정보와 네트워크가 필요 없다.
    from source.common.notion.notion import NotionClient
    from source.config.config import get_env

    packages = json.loads((MOCK_DIR / "service_package_mock.json").read_text(encoding="utf-8"))
    mock_services = json.loads((MOCK_DIR / "service_mock.json").read_text(encoding="utf-8"))
    notion = NotionClient()
    source_id = get_env("NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID")
    services = notion.get_database_rows(get_env("NOTION_SERVICE_DATA_SOURCE_ID"))
    before = notion.get_database_rows(source_id)
    planned = build_plan(packages, mock_services, services, before, args.target)
    print(f"Existing: {len(before)}; adding: {len(planned)}; target: {args.target}", flush=True)
    if not args.apply or not planned:
        return

    for index, row in enumerate(planned, 1):
        started = time.monotonic()
        # 실패/타임아웃은 중단한다. 생성 여부가 불명확할 때 POST를 재시도하지 않는다.
        notion.create_database_row(source_id, row_properties(row))
        if index == 1 or index % 25 == 0 or index == len(planned):
            print(f"Created {index}/{len(planned)}; total {len(before) + index}", flush=True)
        time.sleep(max(0, 0.4 - (time.monotonic() - started)))

    after = notion.get_database_rows(source_id)
    verify_result(before, after, planned)
    print(f"Verified: {len(after)} rows; existing rows unchanged; all new relations valid", flush=True)


if __name__ == "__main__":
    main()
