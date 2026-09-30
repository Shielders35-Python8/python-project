"""
GitHub Advisory 글로벌 보안 권고를 위한 API 를 통해 정보 수집
main 에서 사용할 수 있도록 parse 하여 리턴한다.
"""

import requests, json, os, time
from datetime import datetime
from dotenv import load_dotenv
# 폴더 경로는 main 기준
from source.config.config import get_config
from source.common.slack.notifications import report_error
from source.common.slack.slack import send_task_message

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
        report_error("수집 결과 파일 저장에 실패했습니다.", e, task_name="GitHub 수집")


def get_connection(end_point, retry, dates=[]):
    """
    github advisory 통신 및 통신 에러를 관리하는 함수

    Args: end_point(str), retry(int)
    Return: response
    """

    # 헤더 세팅, .env 에 토큰이 있을 경우 요청 제한 완화를 위하여 추가
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN : headers['Authorization'] = GITHUB_TOKEN

    # 기본 : Global Advisory 중 최신 게시 순 조회
    params = {
        "sort": "updated",
        "direction": "desc",
        "per_page": 100
        #"per_page": 20
    }

    # published param
    match len(dates):
        case 0:
            pass
        case 1:
            start_date = datetime.fromisoformat(dates[0]).strftime("%Y-%m-%d")
            params['published'] = f">={start_date}"
        case 2:
            start_date = datetime.fromisoformat(dates[0]).strftime("%Y-%m-%d")
            end_date = datetime.fromisoformat(dates[1]).strftime("%Y-%m-%d")
            params["published"] = f"{start_date}..{end_date}"

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
            report_error(
                f"GitHub 요청에 실패했습니다 (시도 {attempt + 1}/{retry}).",
                e,
                task_name="GitHub 수집",
            )

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

# cwes.name 부분도 reason으로 평탄화해서 추가 부탁드립니다. -> id 는 필요없으실까여??

# 오늘 할 일 1. 날짜 조건 추가(str), 페이징 하지말고 100건만, resturn 값 정제
# cvss 제거
# 노션 database 에서 제공하는 기능적 한계로 인해 flat 하게 넘김
def get_advisories(dates=None, *, raise_on_error=False):
    """
    Github Advisories 를 갱신일 내림차순으로 최대 100건 조회하고 파싱한다.
    raise_on_error=True이면 수집 실패를 빈 결과와 구분해 호출자에게 전달한다.

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
        response = get_connection(end_point, retry, dates or [])

        # 재시도까지 실패한 요청을 수집 성공으로 알리지 않는다.
        if response is None:
            if raise_on_error:
                raise RuntimeError("GitHub 공지 요청에 실패했습니다.")
            return return_advisories

        # None 검사 후 data parse logic 진행
        if response:
            advisories = response.json()

            for advisory in advisories:
                ghsa_id = advisory.get("ghsa_id")

                package_name = None
                ecosystem = None
                package_version_range = None
                cwe_name = None
                # Notion Database 구조의 한계로 인해 index 0 번째 데이터만 사용
                vulnerabilities = advisory.get("vulnerabilities", {})
                if len(vulnerabilities) > 0 :
                    vulnerability = vulnerabilities[0]
                    package = vulnerability.get("package") or {}
                    package_name = package.get("name")
                    ecosystem = package.get("ecosystem")
                    package_version_range = vulnerability.get("vulnerable_version_range")

                cwes = advisory.get("cwes", {})
                if(len(cwes) > 0):
                    cwe_name = cwes[0].get("name",None)

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
                        "ecosystem": ecosystem,
                        "package_name": package_name,
                        "package_version_range": package_version_range,
                        "reason": cwe_name
                    }
                )

        # 호출 양식 확인용 json 파일 제작, 필요 시에만 주석 해제
        # make_response_json(return_advisories)

        send_task_message(
            f"GitHub 보안 공지 수집이 완료되었습니다. 수집 {len(return_advisories)}건.",
            task_name="GitHub 수집",
        )

    except Exception as e:
        print("get advisories server error > get_advisories > ", e)
        report_error("GitHub 공지 수집 또는 응답 처리에 실패했습니다.", e, task_name="GitHub 수집")
        if raise_on_error:
            raise

    return return_advisories


def example_method():

    get_config("github")

    return "호출확인"
