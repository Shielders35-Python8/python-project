"""기간별 수집 API부터 실제 중복 제거·저장까지 외부 서비스 없이 검증한다."""

from copy import deepcopy
import importlib
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
import requests

from source.common.github_advisory import advisories as github
from source.services import advisory_sync


PERIOD = {"started_at": "2026-09-01", "ended_at": "2026-09-30"}
RAW = {"ghsa_id": "GHSA-new", "summary": "New advisory", "severity": "high",
       "published_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-02T12:34:56Z",
       "vulnerabilities": [], "cwes": []}


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("수집 작업이 끝나지 않았습니다.")
        time.sleep(0.005)


class AdvisorySyncTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("source.common.slack.slack._send_message", return_value=False))
        self.enterContext(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("External HTTP disabled")))
        self.enterContext(patch.object(httpx.Client, "send", side_effect=AssertionError("External HTTP disabled")))
        self.enterContext(patch.object(github.time, "sleep"))
        self.enterContext(patch.object(github, "CONFIG", {"end_point": "https://api.github.com/advisories", "max_retry": 1}))
        self.response = Mock(status_code=200)
        self.response.json.return_value = [dict(RAW, ghsa_id="GHSA-existing"), RAW]
        self.get = self.enterContext(patch.object(github.requests, "get", return_value=self.response))
        self.rows = [{"id": "GHSA-existing", "updated_at": "2026-09-02T12:34:00Z"}]
        self.notion = Mock()
        self.notion.get_database_rows.side_effect = lambda **kwargs: deepcopy(self.rows)
        self.notion.create_database_row.side_effect = self.save
        self.factory = self.enterContext(patch.object(advisory_sync, "NotionClient", return_value=self.notion))
        self.enterContext(patch.object(advisory_sync, "get_env", return_value="advisories-db"))
        self.web = importlib.import_module("source.web.app")
        self.enterContext(patch.object(self.web, "fetch_saved_rows", side_effect=lambda key, *args: deepcopy(self.rows) if key == self.web.ADVISORIES else []))
        self.app = self.web.create_app({"TESTING": True, "DASHBOARD_CACHE_ENABLED": False})
        self.client = self.app.test_client()
        self.runs = self.app.extensions["advisory_sync_runs"]
        self.cache = self.app.extensions["dashboard_cache"]
        self.invalidated = self.enterContext(patch.object(self.cache, "invalidate", wraps=self.cache.invalidate))
        self.release = threading.Event()
        self.release.set()
        self.addCleanup(self.wait_finished)
        self.addCleanup(self.release.set)

    def save(self, data_source_id, properties):
        self.assertTrue(self.release.wait(3))
        self.rows.append({"id": properties["id"]["rich_text"][0]["text"]["content"],
                          "updated_at": properties["updated_at"]["date"]["start"]})

    def wait_finished(self):
        wait_until(lambda: not self.runs.snapshot()["current"] or
                   self.runs.snapshot()["current"]["status"] not in ("queued", "running"))

    def collect(self, period=None):
        response = self.client.post("/api/advisories/sync", json=period or PERIOD)
        self.assertEqual(response.status_code, 202)
        self.wait_finished()
        return self.client.get("/api/advisories/sync-status").json["current"]

    def test_period_reaches_github_and_only_new_rows_are_saved(self):
        run = self.collect()
        self.assertEqual(self.get.call_args.kwargs["params"]["published"], "2026-09-01..2026-09-30")
        self.assertEqual(self.get.call_args.kwargs["params"]["per_page"], 100)
        self.assertEqual((run["status"], run["fetched"], run["skipped"], run["inserted"], run["failed_count"]),
                         ("succeeded", 2, 1, 1, 0))
        self.assertEqual((run["period_start"], run["period_end"]), tuple(PERIOD.values()))
        self.assertIsNotNone(run["finished_at"])
        self.notion.create_database_row.assert_called_once()
        self.notion.client.close.assert_called_once()
        self.invalidated.assert_called_once_with((self.web.ADVISORIES,))
        self.assertEqual(self.client.get("/api/advisories").json["advisory_count"], 2)

    def test_retry_excludes_rows_saved_by_previous_run(self):
        self.collect()
        run = self.collect()
        self.assertEqual((run["status"], run["skipped"], run["inserted"]), ("succeeded", 2, 0))
        self.notion.create_database_row.assert_called_once()

    def test_same_day_range_and_successful_empty_response(self):
        self.response.json.return_value = []
        run = self.collect({"started_at": "2026-09-30", "ended_at": "2026-09-30"})
        self.assertEqual((run["status"], run["fetched"], run["inserted"]), ("succeeded", 0, 0))
        self.assertEqual(self.get.call_args.kwargs["params"]["published"], "2026-09-30..2026-09-30")
        self.notion.get_database_rows.assert_not_called()
        self.notion.create_database_row.assert_not_called()

    def test_invalid_periods_do_not_start_collection(self):
        for payload in [None, [], {}, {"started_at": "2026-09-01"},
                        dict(PERIOD, ended_at="2026-08-31"), dict(PERIOD, started_at="2026-02-30"),
                        dict(PERIOD, started_at="20260901"), dict(PERIOD, ended_at=""),
                        dict(PERIOD, ended_at=123), dict(PERIOD, ended_at=["2026-09-30"]),
                        dict(PERIOD, extra=True)]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/advisories/sync", data=json.dumps(payload), content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.get.assert_not_called()
        self.factory.assert_not_called()
        self.assertIsNone(self.runs.snapshot()["current"])

    def test_requires_same_origin_json_and_rejects_query_options(self):
        for kwargs, code in [({}, 415), ({"json": PERIOD, "headers": {"Origin": "https://other.example"}}, 403),
                             ({"json": PERIOD, "headers": {"Sec-Fetch-Site": "cross-site"}}, 403),
                             ({"data": "broken", "content_type": "application/json"}, 400)]:
            self.assertEqual(self.client.post("/api/advisories/sync", **kwargs).status_code, code)
        self.assertEqual(self.client.post("/api/advisories/sync?extra=1", json=PERIOD).status_code, 400)
        self.assertEqual(self.client.get("/api/advisories/sync").status_code, 405)
        self.get.assert_not_called()

    def test_concurrent_requests_and_status_reads_do_not_collect_twice(self):
        self.release.clear()
        self.assertEqual(self.client.post("/api/advisories/sync", json=PERIOD).status_code, 202)
        responses = []
        def attempt():
            with self.app.test_client() as client:
                responses.append(client.post("/api/advisories/sync", json=PERIOD))
        workers = [threading.Thread(target=attempt) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
        self.assertEqual([response.status_code for response in responses], [409] * 4)
        for _ in range(3):
            response = self.client.get("/api/advisories/sync-status")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.get.call_count, 1)

    def test_upstream_failure_is_not_empty_success_and_can_retry(self):
        self.get.side_effect = requests.Timeout("secret should not reach browser")
        run = self.collect()
        self.assertEqual(run["status"], "failed")
        self.assertNotIn("secret", str(run))
        self.notion.create_database_row.assert_not_called()
        self.get.side_effect = None
        self.assertEqual(self.collect()["status"], "succeeded")

    def test_malformed_github_response_cannot_save_partial_parse(self):
        self.response.json.return_value = [RAW, None]
        self.assertEqual(self.collect()["status"], "failed")
        self.notion.create_database_row.assert_not_called()

    def test_dedup_query_failure_does_not_write(self):
        self.notion.get_database_rows.side_effect = RuntimeError("failed query")
        self.assertEqual(self.collect()["status"], "failed")
        self.notion.create_database_row.assert_not_called()
        self.notion.client.close.assert_called_once()

    def test_partial_save_is_reported_without_raw_errors(self):
        self.response.json.return_value = [RAW, dict(RAW, ghsa_id="GHSA-second")]
        self.notion.create_database_row.side_effect = [None, RuntimeError("secret")]
        run = self.collect()
        self.assertEqual((run["status"], run["inserted"], run["failed_count"]), ("partial", 1, 1))
        self.assertNotIn("secret", str(run))
        self.invalidated.assert_called_once_with((self.web.ADVISORIES,))

    def test_missing_config_does_not_fetch(self):
        with patch.object(advisory_sync, "get_env", return_value=""):
            self.assertEqual(self.collect()["status"], "failed")
        self.get.assert_not_called()

    def test_cache_refetches_saved_advisories(self):
        self.app.config["DASHBOARD_CACHE_ENABLED"] = True
        self.cache.ensure((self.web.ADVISORIES,))
        wait_until(lambda: not self.cache.status((self.web.ADVISORIES,))["refreshing"])
        self.assertEqual(self.client.get("/api/advisories").json["advisory_count"], 1)
        self.collect()
        self.client.get("/api/advisories")
        wait_until(lambda: not self.cache.status((self.web.ADVISORIES,))["refreshing"])
        self.assertEqual(self.client.get("/api/advisories").json["advisory_count"], 2)

    def test_worker_failure_returns_json_and_restores_failed_status(self):
        with patch("source.web.advisory_sync_runs.threading.Thread.start", side_effect=RuntimeError("no worker")):
            response = self.client.post("/api/advisories/sync", json=PERIOD)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.runs.snapshot()["current"]["status"], "failed")
        self.get.assert_not_called()

    def test_pages_show_form_without_starting_collection(self):
        for path in ("/", "/advisories/list"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="sync-start"', response.text)
            self.assertIn('id="sync-end"', response.text)
            self.assertIn("신규 공지 가져오기", response.text)
        status_page = self.client.get("/run-status")
        self.assertEqual(status_page.status_code, 200)
        self.assertNotIn("data-sync-form", status_page.text)
        self.assertNotIn("신규 공지 가져오기", status_page.text)
        self.assertIn("data-run-button", status_page.text)
        self.assertIn("실행 기록", status_page.text)
        self.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
