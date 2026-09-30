"""Notion에서 읽은 공지 행을 중복 제거하고 대시보드용 통계로 집계한다.

외부 조회나 저장을 하지 않는 순수 함수다. 공지 식별자는 GHSA ID, 없으면
Notion page_id, 그것도 없으면 입력 행 위치를 사용한다.
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone


SEVERITIES = ("critical", "high", "medium", "low", "unknown")


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def advisory_key(row: dict, index: int) -> tuple[str, str | int]:
    identifier = _text(row.get("id")).upper()
    return ("id", identifier) if identifier else ("page", _text(row.get("page_id")) or index)


def _published_date(value) -> date | None:
    try:
        timestamp = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp.date()
    except (ValueError, OverflowError):
        return None


def _filter_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except (TypeError, ValueError):
        pass
    raise ValueError("기간은 YYYY-MM-DD 형식의 올바른 날짜로 입력해 주세요.")


def validate_advisory_period(*, started_at=None, ended_at=None) -> tuple[date | None, date | None]:
    """외부 조회 전에 날짜 형식과 범위 순서를 검사한다."""
    start, end = _filter_date(started_at), _filter_date(ended_at)
    if start and end and start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    return start, end


def _bars(counter: Counter) -> list[dict]:
    maximum = max(counter.values(), default=1)
    return [
        {"label": label, "count": count, "width": round(count / maximum * 100, 2)}
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _timeline(dates: list[date]) -> tuple[str, list[dict]]:
    """짧은 기간은 일별, 24개월까지는 월별, 그 이상은 연도별로 빈 구간도 채운다."""
    if not dates:
        return "일별", []
    first, last = min(dates), max(dates)
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    if (last - first).days < 62:
        unit = "일별"
        counts = Counter(day.isoformat() for day in dates)
        keys = [(first + timedelta(days=offset)).isoformat()
                for offset in range((last - first).days + 1)]
    elif months <= 24:
        unit = "월별"
        counts = Counter(day.strftime("%Y-%m") for day in dates)
        first_month = first.year * 12 + first.month - 1
        keys = [f"{month // 12:04d}-{month % 12 + 1:02d}"
                for month in range(first_month, first_month + months)]
    else:
        unit = "연도별"
        counts = Counter(str(day.year) for day in dates)
        keys = [str(year) for year in range(first.year, last.year + 1)]
    maximum = max(counts.values())
    return unit, [
        {"label": key, "short_label": key[5:] if unit == "일별" else key,
         "count": counts[key], "height": round(counts[key] / maximum * 100, 2)}
        for key in keys
    ]


def analyze_advisories(
    rows: list[dict], *, started_at: str | None = None, ended_at: str | None = None,
) -> dict:
    """게시일(UTC) 범위 안의 공지 통계. 시작일과 종료일을 모두 포함한다.

    같은 공지의 심각도가 다르면 가장 높은 알려진 등급을 사용하고, 게시일이
    다르면 가장 이른 유효 날짜를 사용한다. 생태계 및 (생태계, 패키지명)은
    공지 내에서 중복 제거한다. 날짜 없는 공지는 기간 필터가 없을 때만 포함한다.
    """
    start, end = validate_advisory_period(started_at=started_at, ended_at=ended_at)

    grouped = {}
    for index, row in enumerate(rows):
        key = advisory_key(row, index)
        notice = grouped.setdefault(key, {
            "severity": "unknown", "published": None, "ecosystems": set(),
            "packages": set(), "row_count": 0, "missing_id": key[0] != "id",
        })
        notice["row_count"] += 1
        severity = _text(row.get("severity")).lower()
        if severity in SEVERITIES and SEVERITIES.index(severity) < SEVERITIES.index(notice["severity"]):
            notice["severity"] = severity
        published = _published_date(row.get("published_at"))
        if published and (notice["published"] is None or published < notice["published"]):
            notice["published"] = published
        ecosystem = _text(row.get("ecosystem")).lower()
        notice["ecosystems"].add(ecosystem)
        package = _text(row.get("package_name"))
        if package:
            notice["packages"].add((ecosystem, package))

    notices = list(grouped.values())
    undated = sum(notice["published"] is None for notice in notices)
    if start or end:
        notices = [notice for notice in notices if notice["published"] is not None
                   and (start is None or notice["published"] >= start)
                   and (end is None or notice["published"] <= end)]

    total = len(notices)
    severity_counts = Counter(notice["severity"] for notice in notices)
    ecosystem_counts = Counter(eco for notice in notices for eco in notice["ecosystems"])
    package_counts = Counter(package for notice in notices for package in notice["packages"])
    dates = [notice["published"] for notice in notices if notice["published"] is not None]
    timeline_unit, timeline = _timeline(dates)
    high_risk = severity_counts["critical"] + severity_counts["high"]
    maximum_packages = max(package_counts.values(), default=1)

    return {
        "summary": {
            "advisory_count": total,
            "row_count": sum(notice["row_count"] for notice in notices),
            "high_risk_count": high_risk,
            "high_risk_percent": round(high_risk / total * 100, 1) if total else 0,
            "ecosystem_count": sum(bool(eco) for eco in ecosystem_counts),
            "package_count": len(package_counts),
            "undated_count": sum(notice["published"] is None for notice in notices),
            "missing_id_count": sum(notice["missing_id"] for notice in notices),
        },
        "total_advisory_count": len(grouped),
        "excluded_undated_count": undated if start or end else 0,
        "period_start": min(dates).isoformat() if dates else None,
        "period_end": max(dates).isoformat() if dates else None,
        "severity": [
            {"key": severity, "label": "미확인" if severity == "unknown" else severity,
             "count": severity_counts[severity],
             "percent": round(severity_counts[severity] / total * 100, 1) if total else 0}
            for severity in SEVERITIES
        ],
        "ecosystems": _bars(ecosystem_counts),
        "top_packages": [
            {"ecosystem": ecosystem, "name": package, "count": count,
             "width": round(count / maximum_packages * 100, 2)}
            for (ecosystem, package), count in sorted(
                package_counts.items(), key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "timeline_unit": timeline_unit,
        "timeline": timeline,
    }
