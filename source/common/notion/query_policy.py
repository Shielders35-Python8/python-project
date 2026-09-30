"""웹 조회의 요청 간격과 일시적인 Notion 오류 재시도를 조절한다."""

import math
import threading
import time

from notion_client.errors import HTTPResponseError, RequestTimeoutError


def retry_delay(error, default=30):
    headers = getattr(error, "headers", {})
    try:
        value = float(headers.get("Retry-After", default))
        return max(1, value) if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


class QueryDeferred(RuntimeError):
    def __init__(self, seconds):
        super().__init__("Notion 요청 대기 중")
        self.headers = {"Retry-After": str(seconds)}


class NotionQueryPolicy:
    """앱의 모든 조회 작업이 호출 간격과 서버가 지정한 대기 시간을 공유한다."""

    def __init__(self, interval=0.5, attempts=3, clock=time.monotonic, sleep=time.sleep):
        self.interval = interval
        self.attempts = attempts
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.next_request_at = 0

    def call(self, query, **kwargs):
        for attempt in range(self.attempts):
            with self.lock:
                delay = max(0, self.next_request_at - self.clock())
                # 긴 제한은 실패 상태와 재시도 시각으로 표시한다. 작업 스레드를 붙잡지 않는다.
                if delay > 30:
                    raise QueryDeferred(delay)
                if delay:
                    self.sleep(delay)
                self.next_request_at = self.clock() + self.interval
            try:
                return query(**kwargs)
            except (HTTPResponseError, RequestTimeoutError) as error:
                if isinstance(error, HTTPResponseError) and error.status not in (429, 500, 502, 503, 504, 529):
                    raise
                if (getattr(error, "additional_data", None) or {}).get("rate_limit_reason") == "public_api_request_blocked":
                    raise
                delay = max(2 ** attempt, retry_delay(error, default=2 ** attempt))
                with self.lock:
                    self.next_request_at = max(self.next_request_at, self.clock() + delay)
                if attempt == self.attempts - 1 or delay > 30:
                    raise
