"""
프로젝트 메인 스크립트
"""

from source.common.slack.notifications import install_error_notifications, notify_errors

install_error_notifications()

from source.common.github_advisory.advisories import get_advisories, example_method
from source.services.advisory_sync import sync_advisories_to_notion

@notify_errors("프로젝트 실행")
def main():

    print("="*40)
    print("Python Mini Project Start")
    print("="*40)

    # config 값 꺼내기 테스트용 메소드
    # print(example_method())

    # github advisories 호출 및 parsing
    # 아래 함수의 리턴값의 경우, source/example/advisories_response.json 에 예시 올려두었습니다.
    # get advisories -> filtering -> notion insert
    #sync_advisories_to_notion()
    
if __name__ == "__main__":
    main()
