import re


def evaluate_impact(advisories: list[dict], service_packages: list[dict]) -> list[dict]:
    """같은 패키지의 설치 버전과 공지의 취약 버전 범위만 비교한다.

    입력은 팀원의 Notion 조회 함수가 반환하는 일반 딕셔너리 목록이다.
    공지 한 행에는 id, package_name, ecosystem, package_version_range가 들어간다.
    같은 공지에 여러 패키지·취약 범위가 있으면 각각 별도 행으로 전달한다.
    결과 한 항목은 설치 패키지 하나와 취약 버전 범위 하나의 비교다.
    version_matches는 범위 안이면 True, 밖이면 False, 해석 불가이면 None이다.
    pip의 숫자 버전(예: 1.2.10)과 쉼표로 연결된 비교 조건을 지원한다.
    프리릴리스·와일드카드 등은 None으로 남긴다. 점수와 운영 상태는 다루지 않는다.
    """
    # 팀원 구현 후 호출하는 쪽에서 조회 결과를 인자로 전달한다.
    # advisories = notion_repository.get_advisories()
    # service_packages = notion_repository.get_service_packages()

    results = []
    for advisory in advisories:
        target_name = advisory["package_name"]
        ecosystem = advisory["ecosystem"]
        version_range = advisory.get("package_version_range")
        if ecosystem == "pip":
            target_name = re.sub(r"[-_.]+", "-", target_name).lower()

        for package in service_packages:
            package_name = package["package_name"]
            if package["ecosystem"] == "pip":
                package_name = re.sub(r"[-_.]+", "-", package_name).lower()
            if package["ecosystem"] != ecosystem or package_name != target_name:
                continue

            installed_version = package.get("installed_version")
            version_matches = None
            if (
                package["ecosystem"] == "pip"
                and isinstance(installed_version, str)
                and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", installed_version)
                and isinstance(version_range, str)
            ):
                checks = []
                for condition in version_range.split(","):
                    match = re.fullmatch(
                        r"\s*(<=|>=|==|!=|<|>|=)\s*([0-9]+(?:\.[0-9]+)*)\s*",
                        condition,
                    )
                    if match is None:
                        checks = []
                        break
                    operator, boundary = match.groups()
                    installed = tuple(map(int, installed_version.split(".")))
                    limit = tuple(map(int, boundary.split(".")))
                    # 1.10 > 1.9, 1.2 == 1.2.0이 되도록 숫자별로 비교한다.
                    length = max(len(installed), len(limit))
                    installed += (0,) * (length - len(installed))
                    limit += (0,) * (length - len(limit))
                    checks.append(
                        {
                            "<": installed < limit,
                            "<=": installed <= limit,
                            ">": installed > limit,
                            ">=": installed >= limit,
                            "==": installed == limit,
                            "=": installed == limit,
                            "!=": installed != limit,
                        }[operator]
                    )
                if checks:
                    version_matches = all(checks)

            results.append(
                {
                    "advisory_id": advisory["id"],
                    "service_id": package["service_id"],
                    "package_name": package["package_name"],
                    "installed_version": installed_version,
                    "package_version_range": version_range,
                    "version_matches": version_matches,
                }
            )

    # 팀원 구현 후 연결할 결과 저장 호출 예시.
    # notion_repository.save_comparison_results(results)
    return results
