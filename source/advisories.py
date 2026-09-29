"""
GitHub Advisory 글로벌 보안 권고를 위한 API 를 통해 정보 수집
main 에서 사용할 수 있도록 parse 하여 리턴한다.
"""

import requests
import json

# 폴더 경로는 main 기준
from source.config.config import get_config


def make_response_json(return_advisories):
    """
    파싱한 github advisory 데이터를 json 파일로 저장하는 함수

    Args: return_advisories(dict)
    """
    try:
        with open(
            "source/example/advisories_response.json", "w", encoding="utf-8"
        ) as file:
            json.dump(return_advisories, file, indent=4)
            print("저장 완료 : advisories_response.json")
    except Exception as e:
        print("get advisories return value save error > make_response_json > ", e)


def get_connection(end_point, retry):
    """
    github advisory 통신 및 통신 에러를 관리하는 함수

    Args: end_point(str), retry(int)
    Return: response
    """
    # 헤더 세팅
    headers = {"Accept": "application/vnd.github+json"}

    # 날짜 필터 없이 전체 Global Advisory 중 최신 게시 순 100 건 조회
    params = {
        "sort": "published",
        "direction": "desc",
        "per_page": 20,
    }

    # 프로젝트의 기본이 되는 data 이기 때문에 retry 로직 추가
    for attempt in range(retry):
        try:
            response = requests.get(
                end_point, headers=headers, params=params, timeout=10
            )

            response.raise_for_status()

            return response

        # 예외 상황 log 를 자세히 남겨야 파악 및 조치가 편함
        except Exception as e:
            print("get advisories connection error > get_connection")

            if isinstance(e, requests.exceptions.HTTPError):
                status = e.response.status_code

                if status in (400, 401, 403, 404):
                    # 해당 에러들의 경우 client error 이므로 연동 정보 재확인이 필요하여 break
                    print(f"Client Error (retry : {attempt + 1}/3)")
                    break
                elif status >= 500:
                    print(f"Github Server Error (retry : {attempt + 1}/3)")
                else:
                    print(f"Unexpected Http Error (retry : {attempt + 1}/3)")

            elif isinstance(e, requests.exceptions.ConnectionError):
                print(f"Github Server Connection Error (retry : {attempt + 1}/3)")
            elif isinstance(e, requests.exceptions.Timeout):
                print(f"Github Server Timeout Error (retry : {attempt + 1}/3)")
            else:
                print(f"Unexpected Server Error (retry : {attempt + 1}/3)")


# yusung:
# get_connection params에 날짜 범위로직으로 수정 제안드립니다.. 날짜 범위는 args고정이 아니고 함수 호출부에서 인자로 넘길 수 있게 요청드립니다.
# 일일 cron 돌리고, 00:00 ~ 23:59:59 까지의 updated_at 기준으로 변경사항 체크해서 서비스 패키지 업데이트 하는 방식으로 진행하려 합니다.
# advisories 응답에서 vulnerabilities[*].package.name, vulnerabilities[*].package.ecosystem, vulnerable_version_range 가 있어야 서비스 패키지 mock과 비교하여 취약점 반영 업데이트가 가능합니다.
# package_name, ecosystem, package_version_range로 flattening 해주시면 감사하겠습니다.
# cvss_score도 cvss_severities.cvss_v3.score 부분 빼서 추가 부탁드립니다. cvss_v4는 최신 기준이라 신뢰할 수 없는 데이터라서 cvss_v3로 작업하겠습니다.
# cwes.name 부분도 reason으로 평탄화해서 추가 부탁드립니다. 보안 위험의 이유가 설명되어있기 때문에 취약점 원인 설명 summary라고 보면 될 것 같습니다.
# source 필드는 삭제부탁드립니다.
# summary 필드는 response의 summary를 title로 사용했으니 삭제부탁드립니다. description 길이가 html_url 의 내용을 전부 넣어놓은거라
# 차라리 링크를 통해 이동해서 보는게 효율적입니다.
def get_advisories():
    """
    Github Advisories 를 최신 30건 조회하고 파싱하여 리턴하는 함수

    Return:  return_advisories(list(dict))
    """
    return_advisories = []
    try:
        # config 에 end_point 가 없을 경우 runtime error 리턴
        config = get_config("github")
        end_point = config.get("end_point")
        if not end_point:
            raise RuntimeError("github advisory endpoint 확인 필요")

        # 재시도 횟수
        retry = config.get("max_retry")

        # github 통신
        response = get_connection(end_point, retry)

        # None 검사 후 data parse logic 진행
        if response:
            advisories = response.json()
            for advisory in advisories:
                ghsa_id = advisory.get("ghsa_id")

                return_advisories.append(
                    {
                        "id": ghsa_id,
                        "source": "github_advisory",  # 여기 삭제 부탁드립니다.
                        "title": advisory.get("summary", ghsa_id),
                        "url": advisory.get(
                            "html_url", f"https://github.com/advisories/{ghsa_id}"
                        ),
                        # yusung: published_at 으로 칼럼 통일 부탁드립니다.
                        "published": advisory.get("published_at"),
                        "updated_at": advisory.get("updated_at"),
                        "severity": advisory.get("severity"),
                        "summary": (
                            advisory.get("description") or ""
                        ),  # 여기 삭제 부탁드립니다.
                        "cve_id": advisory.get("cve_id"),
                        # "ecosystem"
                        # "package_name"
                        # "package_version_range"
                        # "reason"
                    }
                )

        # 호출 양식 확인용 json 파일 제작, 필요 시에만 주석 해제
        # make_response_json(return_advisories)

    except Exception as e:
        print("get advisories server error > get_advisories > ", e)

    return return_advisories


def example_method():

    get_config("github")

    return "호출확인"
