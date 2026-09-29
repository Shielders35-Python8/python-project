import time
from datetime import datetime, timedelta, timezone

from source.advisories import get_advisories


def daily_get_advisories() -> None:
    """프로그램이 실행 중인 동안 한국 시간으로 매일 자정에 공지를 수집한다.

    다음 자정까지 기다린 뒤 get_advisories()를 호출하고 반복한다.
    실행을 끝내려면 Ctrl+C로 중단한다.
    전날 데이터만 조회하는 날짜 필터는 수집 담당 함수에서 처리할 부분이다.
    현재 get_advisories()는 날짜 필터 없이 최신 20건을 반환한다.
    """
    korea_timezone = timezone(timedelta(hours=9))

    while True:
        now = datetime.now(korea_timezone)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        time.sleep((next_midnight - now).total_seconds())

        try:
            advisories = get_advisories()
            # 팀원의 저장 함수가 완성되면 연결한다.
            # notion_repository.save_advisories(advisories)
        except Exception as error:
            print(f"일간 공지 수집 실패: {error}")
