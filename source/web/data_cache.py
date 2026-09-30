"""전체 조회를 요청 경로에서 분리하고 마지막 성공 결과를 보존하는 메모리 캐시."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time

from source.common.notion.query_policy import retry_delay


class CacheUnavailable(RuntimeError):
    pass


@dataclass
class Entry:
    rows: list | None = None
    expires_at: float = 0
    retry_at: float = 0
    refreshing: bool = False
    failed: bool = False
    version: int = 0
    updated_at: str | None = None
    last_started_at: float = float("-inf")
    generation: int = 0


class DashboardDataCache:
    def __init__(self, loader, ttl=60, failure_ttl=30, clock=time.monotonic):
        self.loader = loader
        self.ttl = ttl
        self.failure_ttl = failure_ttl
        self.clock = clock
        self.entries = {}
        self.lock = threading.Lock()

    def ensure(self, keys, *, force=False):
        """같은 소스의 동시 요청은 하나의 작업으로 합치고 즉시 상태를 돌려준다."""
        with self.lock:
            now = self.clock()
            for key in keys:
                entry = self.entries.setdefault(key, Entry())
                due = entry.rows is None or now >= entry.expires_at
                manual = force and now - entry.last_started_at >= 5
                if (due or manual) and not entry.refreshing and now >= entry.retry_at:
                    entry.refreshing = True
                    entry.last_started_at = now
                    worker = threading.Thread(target=self._refresh, args=(key, entry.generation), daemon=True,
                                              name="dashboard-data-refresh")
                    try:
                        worker.start()
                    except Exception:
                        entry.refreshing = False
                        entry.failed = True
                        entry.retry_at = now + self.failure_ttl
            return self._status(keys)

    def invalidate(self, keys):
        """저장 이후 다시 조회한다. 저장 전 시작한 조회가 새 결과를 덮지 않게 한다."""
        with self.lock:
            for key in keys:
                entry = self.entries.setdefault(key, Entry())
                entry.generation += 1
                entry.expires_at = 0
                entry.retry_at = 0

    def _refresh(self, key, generation):
        failed = None
        try:
            rows = self.loader(key)
        except Exception as error:
            failed = error
        with self.lock:
            entry = self.entries[key]
            invalidated = generation != entry.generation
            entry.refreshing = False
            if invalidated:
                pass  # 저장 전에 시작한 조회 결과(또는 오류)는 사용하지 않는다.
            elif failed is not None:
                entry.failed = True
                entry.retry_at = self.clock() + max(self.failure_ttl, retry_delay(failed))
            else:
                # 페이지 전체 조회가 성공한 경우에만 이전 스냅샷을 교체한다.
                entry.rows = rows
                entry.expires_at = self.clock() + self.ttl
                entry.retry_at = 0
                entry.failed = False
                entry.refreshing = False
                entry.version += 1
                entry.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if invalidated:
            self.ensure((key,))
        elif failed is not None:
            logging.getLogger(__name__).warning("대시보드 갱신 실패 (%s): %s", key, type(failed).__name__)

    def read(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None or entry.rows is None:
                raise CacheUnavailable("Notion 데이터를 아직 불러오지 못했습니다.")
            # 소비자는 스냅샷을 읽기만 하며 화면 데이터는 별도로 만든다.
            return entry.rows

    def status(self, keys):
        with self.lock:
            return self._status(keys)

    def _status(self, keys):
        entries = [self.entries.get(key, Entry()) for key in keys]
        timestamps = [entry.updated_at for entry in entries if entry.updated_at]
        return {
            "loading": any(entry.rows is None and entry.refreshing for entry in entries),
            "refreshing": any(entry.refreshing for entry in entries),
            "ready": all(entry.rows is not None for entry in entries),
            "failed": any(entry.failed for entry in entries),
            "stale": any(entry.rows is not None and self.clock() >= entry.expires_at for entry in entries),
            "version": ":".join(str(entry.version) for entry in entries),
            "updated_at": min(timestamps) if timestamps else None,
        }
