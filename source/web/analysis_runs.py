"""한 서버 프로세스에서 취약도 분석을 한 번에 하나씩 실행한다."""

from copy import deepcopy
from datetime import datetime, timezone
import logging
import threading
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalysisRuns:
    def __init__(self, runner, on_finish):
        self.runner = runner
        self.on_finish = on_finish
        self.lock = threading.Lock()
        self.runs = []

    def snapshot(self):
        with self.lock:
            return deepcopy({"current": self.runs[0] if self.runs else None, "history": self.runs})

    def start(self):
        with self.lock:
            if self.runs and self.runs[0]["status"] in ("queued", "running"):
                return False, deepcopy(self.runs[0])
            run = {"id": uuid4().hex, "status": "queued", "stage": "queued",
                   "message": "분석 시작을 기다리고 있습니다.", "started_at": timestamp(),
                   "finished_at": None, "advisory_count": None, "package_count": None,
                   "matched_count": None, "affected_count": None, "unknown_count": None,
                   "updated_count": 0, "total_updates": None}
            self.runs.insert(0, run)
            del self.runs[20:]
            worker = threading.Thread(target=self._execute, args=(run,), daemon=True,
                                      name="vulnerability-analysis")
            try:
                worker.start()
            except Exception:
                run.update(status="failed", stage="failed", finished_at=timestamp(),
                           message="분석을 시작하지 못했습니다. 잠시 후 다시 실행해 주세요.")
                raise
            return True, deepcopy(run)

    def _execute(self, run):
        def progress(**values):
            with self.lock:
                run.update(values, status="running")

        progress(stage="loading", message="저장된 Notion 데이터를 불러오고 있습니다.")
        try:
            summary = self.runner(progress)
        except Exception as error:
            # 원문 예외에는 인증 정보나 외부 응답이 포함될 수 있다.
            logging.getLogger(__name__).warning("취약도 분석 실패: %s", type(error).__name__)
            outcome = {"status": "failed", "stage": "failed",
                       "message": "분석에 실패했습니다. 일부 결과가 저장되었을 수 있으니 저장 건수와 서버 로그를 확인해 주세요."}
        else:
            outcome = {**summary, "status": "succeeded", "stage": "done",
                       "message": "분석과 Notion 저장이 완료되었습니다."}
        finally:
            # 실패한 경우에도 이미 저장된 패키지가 있을 수 있어 조회 캐시를 무효화한다.
            try:
                self.on_finish()
            except Exception as error:
                logging.getLogger(__name__).warning("분석 후 화면 갱신 준비 실패: %s", type(error).__name__)
                outcome["message"] += " 화면 갱신에 실패했습니다. 잠시 후 새로고침해 주세요."
        with self.lock:
            run.update(outcome, finished_at=timestamp())
