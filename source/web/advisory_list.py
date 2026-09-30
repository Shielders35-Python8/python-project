"""Notion 공지 행을 목록으로 정리한다. 외부 조회나 저장은 실행하지 않는다."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from source.services.advisory_analysis import advisory_key


def _parse_date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _date_sort_key(value):
    return _parse_date(value) or datetime.min.replace(tzinfo=timezone.utc)


def _source_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def build_saved_advisories(rows: list[dict]) -> list[dict]:
    """공지별로 묶되 패키지·취약 범위는 모두 보존하고 최신 게시일순으로 정렬한다."""
    grouped = {}
    # 같은 공지의 메타데이터가 다르면 가장 최근에 갱신된 행을 우선한다.
    indexed_rows = sorted(enumerate(rows), key=lambda item: (
        _date_sort_key(item[1].get("updated_at")),
        _date_sort_key(item[1].get("published_at")),
    ), reverse=True)
    for index, row in indexed_rows:
        key = advisory_key(row, index)
        if key not in grouped:
            grouped[key] = {
                "id": key[1] if key[0] == "id" else None,
                "title": None, "url": None, "severity": None, "cve_id": None,
                "published_at": None, "updated_at": None, "packages": [],
            }
        advisory = grouped[key]
        for field in ("title", "severity", "cve_id", "published_at", "updated_at"):
            if not advisory[field] and row.get(field):
                advisory[field] = row[field]
        if not advisory["url"]:
            advisory["url"] = _source_url(row.get("url"))
        package = {field: row.get(field) for field in (
            "ecosystem", "package_name", "package_version_range",
        )}
        if any(package.values()) and package not in advisory["packages"]:
            advisory["packages"].append(package)
    advisories = list(grouped.values())
    for advisory in advisories:
        advisory["title"] = advisory["title"] or advisory["id"] or "제목 미설정"
        for field in ("published", "updated"):
            parsed = _parse_date(advisory[f"{field}_at"])
            advisory[f"{field}_date"] = parsed.date().isoformat() if parsed else None
        advisory["severity_kind"] = (advisory["severity"] or "").strip().lower()
    advisories.sort(key=lambda advisory: (
        _date_sort_key(advisory["published_at"]),
        _date_sort_key(advisory["updated_at"]),
        advisory["id"] or "",
    ), reverse=True)
    return advisories
