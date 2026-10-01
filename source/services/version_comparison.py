"""GitHub 공지의 비교 조건을 패키지 생태계별 버전 순서로 평가한다."""

import operator
import re

from packaging.version import Version as PythonVersion
from semver import Version as SemVerVersion
from univers.nuget import InvalidNuGetVersion
from univers.versions import MavenVersion, NugetVersion, RubygemsVersion


NUMERIC_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*")
VERSION_TOKEN = re.compile(r"[vV]?[0-9][0-9A-Za-z.!+_-]*")
COMPARISONS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
    "=": operator.eq, "==": operator.eq, "!=": operator.ne,
}
ECOSYSTEM_ALIASES = {
    "pypi": "pip", "python": "pip", "gem": "rubygems", "ruby": "rubygems",
    "cargo": "rust", "golang": "go", "hex": "erlang", "hex.pm": "erlang",
    "github actions": "actions", "github-actions": "actions", "githubactions": "actions",
    "packagist": "composer", "dart": "pub",
}


def normalize_ecosystem(ecosystem) -> str:
    value = ecosystem.strip().lower() if isinstance(ecosystem, str) else ""
    return ECOSYSTEM_ALIASES.get(value, value)


def _numeric_version(version: str) -> tuple[int, ...]:
    parts = tuple(map(int, version.split(".")))
    while parts and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def _semver_version(version: str) -> SemVerVersion:
    match = re.fullmatch(r"[vV]?([0-9]+(?:\.[0-9]+){0,2})([-+].*)?", version)
    if match is None:
        raise ValueError("지원하지 않는 SemVer 표기")
    core, suffix = match.groups()
    parts = core.split(".")
    # GitHub 공지의 1, 1.2 상한은 기존처럼 빠진 자리를 0으로 보완한다.
    return SemVerVersion.parse(".".join(parts + ["0"] * (3 - len(parts))) + (suffix or ""))


def _identifier_key(suffix: str | None) -> tuple:
    return tuple((0, int(part)) if part.isdigit() else (1, part)
                 for part in suffix.split(".")) if suffix else ()


def _maven_version(version: str) -> MavenVersion:
    # univers 32.0.1의 별칭 목록에 빠진 Maven release == final == ga를 보완한다.
    normalized = re.sub(r"(?<![A-Za-z])release(?![A-Za-z])", "final", version, flags=re.IGNORECASE)
    return MavenVersion(normalized)


def _pub_version(version: str) -> tuple:
    # Pub은 SemVer와 달리 빌드 식별자도 숫자/문자 순서로 비교한다.
    # https://pub.dev/packages/pub_semver#semantics
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+){0,2})"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", version,
    )
    if match is None:
        raise ValueError("지원하지 않는 Pub 표기")
    core, prerelease, build = match.groups()
    parts = tuple(map(int, core.split(".")))
    return (parts + (0,) * (3 - len(parts)), prerelease is None,
            _identifier_key(prerelease), _identifier_key(build))


def _composer_version(version: str) -> tuple:
    # Composer의 릴리스 정규화와 PHP의 dev < alpha < beta < RC < stable < patch 순서.
    # https://github.com/composer/semver/blob/main/src/VersionParser.php
    # 이름만 있는 dev-main 등의 브랜치는 릴리스와 순서를 정할 수 없어 제외한다.
    match = re.fullmatch(
        r"v?([0-9]+(?:\.[0-9]+){0,3})"
        r"(?:[._-]?(stable|alpha|a|beta|b|rc|patch|pl|p)([0-9]*(?:[.-][0-9]+)*))?"
        r"([.-]?dev)?(?:\+[0-9a-z._-]+)?", version, re.IGNORECASE,
    )
    if match is None:
        raise ValueError("지원하지 않는 Composer 릴리스 표기")
    core, stability, number, dev = match.groups()
    parts = tuple(map(int, core.split(".")))
    stability = (stability or ("dev" if dev else "stable")).lower()
    ranks = {"dev": -4, "alpha": -3, "a": -3, "beta": -2, "b": -2,
             "rc": -1, "stable": 0, "patch": 1, "pl": 1, "p": 1}
    serial = tuple(map(int, re.findall(r"[0-9]+", number or "")))
    if stability == "stable":
        serial, dev = (), None
    return parts + (0,) * (4 - len(parts)), ranks[stability], serial, not bool(dev)


VERSION_PARSERS = {
    "pip": PythonVersion,
    "npm": _semver_version,
    "nuget": NugetVersion,
    "maven": _maven_version,
    "rubygems": RubygemsVersion,
    "composer": _composer_version,
    "go": _semver_version,  # v 접두사와 timestamp/hash가 포함된 pseudo-version도 SemVer 순서
    "rust": _semver_version,
    "erlang": _semver_version,
    "actions": _semver_version,
    "swift": _semver_version,
    "pub": _pub_version,
    "other": _semver_version,
}


def version_matches_range(version, version_range, ecosystem: str | None = None) -> bool | None:
    """모든 쉼표 조건의 포함 여부. 형식/순서를 알 수 없으면 None을 반환한다.

    생태계별 릴리스 순서를 적용하며 설치 도구의 사전 릴리스 자동 제외는 하지 않는다.
    other/미등록 생태계는 숫자 또는 SemVer만 처리하고 임의 태그를 추측하지 않는다.
    """
    if not isinstance(version, str) or not isinstance(version_range, str):
        return None
    if ecosystem is not None and not isinstance(ecosystem, str):
        return None
    version = version.strip()
    conditions = []
    expression = version_range.translate(str.maketrans({"≤": "<=", "≥": ">=", "≠": "!="}))
    for condition in expression.split(","):
        match = re.fullmatch(r"\s*(<=|>=|==|!=|<|>|=)?\s*(\S+)\s*", condition)
        if match is None:
            return None
        comparison, boundary = match.groups()
        conditions.append((comparison or "==", boundary))

    versions = [version] + [boundary for _, boundary in conditions]
    # Maven 등의 관대한 파서가 지원하지 않는 범위 기호까지 버전명으로 해석하지 않게 한다.
    if any(not VERSION_TOKEN.fullmatch(value) or ".." in value or value.endswith(".")
           for value in versions):
        return None
    parse = VERSION_PARSERS.get(normalize_ecosystem(ecosystem), _semver_version)
    if parse is _semver_version and all(NUMERIC_VERSION.fullmatch(value) for value in versions):
        parse = _numeric_version  # 기존 숫자·점 버전의 0 보완과 네 자리 이상 비교를 유지
    try:
        installed = parse(version)
        # 조건 순서에 상관없이 모든 경계를 먼저 검증한다.
        limits = [(comparison, parse(boundary)) for comparison, boundary in conditions]
        return all(COMPARISONS[comparison](installed, limit) for comparison, limit in limits)
    except (ValueError, InvalidNuGetVersion):
        return None
