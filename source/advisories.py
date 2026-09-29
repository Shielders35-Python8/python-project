"""
    GitHub Advisory 글로벌 보안 권고를 위한 API 를 통해 정보 수집
    main 에서 사용할 수 있도록 parse 하여 리턴한다.
"""
import requests
# 폴더 경로는 main 기준
from source.config.config import get_config

def get_advisories():
    end_point = get_config("github")
    print(end_point)
    # headers = {
    #     "Accept": "application/vnd.github+json"
    # }
    # # 날짜 필터 없이 전체 Global Advisory 중 최신 게시 순 100 건 조회
    # params = {
    #     "sort": "published",
    #     "direction": "desc",
    #     "per_page": 100,
    # }
    # response = requests.get(
    #     end_point,
    #     headers=headers,
    #     params=params,
    #     timeout=10
    # )

    # response.raise_for_status()

    # advisories = response.json()
    # for item in advisories:
    #     print(item)

def example_method():

    get_config("github")
    
    return '호출확인'