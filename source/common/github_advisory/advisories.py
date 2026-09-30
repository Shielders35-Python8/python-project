"""
GitHub Advisory 글로벌 보안 권고를 위한 API 를 통해 정보 수집
main 에서 사용할 수 있도록 parse 하여 리턴한다.
"""

import requests, json, os, time
from datetime import datetime
from dotenv import load_dotenv
# 폴더 경로는 main 기준
from source.config.config import get_config

# Config, env 등 전역으로 선언하여 프로젝트 로드 시에만 수집
load_dotenv()
CONFIG = get_config("github")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

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


def get_connection(end_point, retry, *dates):
    """
    github advisory 통신 및 통신 에러를 관리하는 함수

    Args: end_point(str), retry(int)
    Return: response
    """

    # 헤더 세팅, .env 에 토큰이 있을 경우 요청 제한 완화를 위하여 추가
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN : headers['Authorization'] = GITHUB_TOKEN

    # 기본 : 날짜 필터 없이 전체 Global Advisory 중 최신 게시 순 100 건 조회
    params = {
        "sort": "published",
        "direction": "desc",
        "per_page": 20,
    }

    # published param
    match len(dates):
        case 0:
            pass
        case 1:
            params['published'] = f">={dates[0]}"
        case 2:
            params["published"] = f"{dates[0]}..{dates[1]}"

    print("param > ", params)

    # 프로젝트의 기본이 되는 data 이기 때문에 retry 로직 추가
    for attempt in range(retry):
        try:
            response = requests.get(
                end_point, headers=headers, params=params, timeout=5
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

            # 재시도 전 0.5 초간 sleep
            time.sleep(0.5)


# yusung:
# get_connection params에 날짜 범위로직으로 수정 제안드립니다.. 
# 날짜 범위는 args고정이 아니고 함수 호출부에서 인자로 넘길 수 있게 요청드립니다.
# 일일 cron 돌리고, 00:00 ~ 23:59:59 까지의 updated_at 기준으로 
# 변경사항 체크해서 서비스 패키지 업데이트 하는 방식으로 진행하려 합니다.

# -> *args 에 보낼 자료형 string인지, datetime 인지 부탁드림다

# advisories 응답에서 vulnerabilities[*].package.name, 
# vulnerabilities[*].package.ecosystem, vulnerable_version_range 가 있어야 
# 서비스 패키지 mock과 비교하여 취약점 반영 업데이트가 가능합니다.
# package_name, ecosystem, package_version_range로 flattening 해주시면 감사하겠습니다.
# cvss_score도 cvss_severities.cvss_v3.score 부분 빼서 추가 부탁드립니다. 
# cvss_v4는 최신 기준이라 신뢰할 수 없는 데이터라서 cvss_v3로 작업하겠습니다.
# cwes.name 부분도 reason으로 평탄화해서 추가 부탁드립니다. -> id 는 필요없으실까여??

# -> vulnerabilities, cvss 가 원본이 list 이고 상이한 값이 들어있을 수 있는데, 
# 상이한 값이 들어있을 경우에는 같은 id 에  vulnerabilities, cwes 만 다르게 넣어드리면 될까요??
# 이렇게 한다면 저 두 list 의 길이가 상이한 경우가 있어서 기준이 필요하고 효율적이지 않습니다.
# cwes id 없이 name 만 받으시나여
# advisories_mock 의 page_id 는 Notion 파트에서 에서 추가할 부분인거져?? 
# Notion db 읽어와서 이미 있는 ghsa_id 는 필터링해서 리턴할까 했는데

# 보안 위험의 이유가 설명되어있기 때문에 취약점 원인 설명 summary라고 보면 될 것 같습니다.
# source 필드는 삭제부탁드립니다.
# summary 필드는 response의 summary를 title로 사용했으니 삭제부탁드립니다. 
# description 길이가 html_url 의 내용을 전부 넣어놓은거라
# 차라리 링크를 통해 이동해서 보는게 효율적입니다.

# 날짜로 걸면 페이지네이션 추가해서 전체 데이터 읽어오겠습니당

# 오늘 할 일 1. 날짜 조건 추가(str), 페이징 하지말고 100건만, resturn 값 정제
# cvss 제거
# 노션 database 에서 제공하는 기능적 한계로 인해 flat 하게 넘김
def get_advisories(*dates):
    """
    Github Advisories 를 최신 30건 조회하고 파싱하여 리턴하는 함수

    Return:  return_advisories(list(dict))
    """
    return_advisories = []
    try:
        # config 에 end_point 가 없을 경우 runtime error 리턴
        
        end_point = CONFIG.get("end_point")
        if not end_point:
            raise RuntimeError("github advisory endpoint 확인 필요")

        # 재시도 횟수
        retry = CONFIG.get("max_retry", 3)

        # github 통신
        response = get_connection(end_point, retry, *dates)

        # None 검사 후 data parse logic 진행
        if response:
            advisories = response.json()
            for advisory in advisories:
                ghsa_id = advisory.get("ghsa_id")
                cvss_score = advisory.get("cvss_severities").get("cvss_v3").get("score")

                vulnerabilities = []
                for vulnerability in advisory.get("vulnerabilities"):
                    vulnerability = {
                        "package_name": vulnerability.get("package").get("name"),
                        "ecosystem": vulnerability.get("package").get("ecosystem"),
                        "package_version_range": vulnerability.get("vulnerable_version_range")
                    }

                return_advisories.append(
                    {
                        "id": ghsa_id,
                        "title": advisory.get("summary", ghsa_id),
                        "url": advisory.get(
                            "html_url", f"https://github.com/advisories/{ghsa_id}"
                        ),
                        "published_at": advisory.get("published_at"),
                        "updated_at": advisory.get("updated_at"),
                        "severity": advisory.get("severity"),
                        "cve_id": advisory.get("cve_id"),
                        # "ecosystem"
                        # "package_name"
                        # "package_version_range"
                        # "reason"- cwes.name 
                        # cvss_severities
                        #"cvss_score" : cvss_score
                    }
                )

        # 호출 양식 확인용 json 파일 제작, 필요 시에만 주석 해제
        make_response_json(return_advisories)

    except Exception as e:
        print("get advisories server error > get_advisories > ", e)

    return return_advisories


def example_method():

    get_config("github")

    return "호출확인"
