"""공지 수집을 백그라운드에서 실행하고 가장 최근 작업 상태를 보관한다."""

from copy import deepcopy
import logging
import threading
from uuid import uuid4

from source.web.analysis_runs import timestamp


class AdvisorySyncRuns:
    def __init__(self, runner, on_finish):
        self.runner = runner
        self.on_finish = on_finish
        self.lock = threading.Lock()
        self.current = None

    def snapshot(self):
        with self.lock:
            return {"current": deepcopy(self.current)}

    def start(self, started_at, ended_at):
        with self.lock:
            if self.current and self.current["status"] in ("queued", "running"):
                return False, deepcopy(self.current)
            run = {"id": uuid4().hex, "status": "queued", "stage": "queued",
                   "message": "공지 수집 시작을 기다리고 있습니다.",
                   "started_at": timestamp(), "finished_at": None,
                   "period_start": started_at, "period_end": ended_at,
                   "fetched": None, "skipped": None, "total": None,
                   "inserted": 0, "failed_count": 0}
            self.current = run
            worker = threading.Thread(target=self._execute, args=(run,), daemon=True,
                                      name="advisory-sync")
            try:
                worker.start()
            except Exception:
                run.update(status="failed", stage="failed", finished_at=timestamp(),
                           message="수집을 시작하지 못했습니다. 다시 시도해 주세요.")
                raise
            return True, deepcopy(run)

    def _execute(self, run):
        def progress(**values):
            with self.lock:
                run.update(values, status="running")

        try:
            summary = self.runner([run["period_start"], run["period_end"]], progress)
            failed = len(summary["failed"])
            outcome = {"fetched": summary["fetched"], "skipped": summary["skipped"],
                       "inserted": summary["inserted"], "failed_count": failed,
                       "status": "partial" if failed else "succeeded", "stage": "done",
                       "message": "일부 공지 저장에 실패했습니다. 같은 기간으로 다시 수집할 수 있습니다."
                       if failed else "공지 수집과 Notion 저장이 완료되었습니다."}
        except Exception as error:
            logging.getLogger(__name__).warning("공지 수집 실패: %s", type(error).__name__)
            outcome = {"status": "failed", "stage": "failed",
                       "message": "공지 수집에 실패했습니다. 저장 건수와 서버 로그를 확인한 뒤 다시 시도해 주세요."}
        finally:
            # 일부 저장 후 실패한 경우에도 화면이 새 데이터를 조회하도록 한다.
            try:
                self.on_finish()
            except Exception as error:
                logging.getLogger(__name__).warning("수집 후 화면 갱신 준비 실패: %s", type(error).__name__)
                outcome["message"] += " 화면 갱신에 실패했습니다. 새로고침해 주세요."
        with self.lock:
            run.update(outcome, finished_at=timestamp())
