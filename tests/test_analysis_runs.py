"""실제 분석 함수와 웹 실행/상태/결과 연결을 외부 요청 없이 검증한다."""

from copy import deepcopy
import importlib
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx

from source.services import processor
from source.common.notion.notion import NotionClient
from source.web.data_cache import DashboardDataCache


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("분석 작업이 끝나지 않았습니다.")
        time.sleep(0.005)


class AnalysisRunTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("source.common.slack.slack._send_message", return_value=False))
        self.enterContext(patch.object(httpx.Client, "send", side_effect=AssertionError("External HTTP disabled")))
        self.web = importlib.import_module("source.web.app")
        self.release = threading.Event()
        self.release.set()
        self.advisories = [
            {"package_name": "demo", "ecosystem": "npm", "package_version_range": "<2", "severity": "critical"},
            {"package_name": "demo", "ecosystem": "npm", "package_version_range": "<2", "severity": "low"},
            {"package_name": "unknown", "ecosystem": "npm", "package_version_range": "<2.0-rc.1", "severity": "high"},
        ]
        self.packages = [dict(page_id=name, package_name=name, package_version="1.0",
                              ecosystem="npm", vulnerability="safe", service_id=[])
                         for name in ("demo", "unknown", "untouched")]
        self.notion = Mock()
        self.notion.get_database_rows.side_effect = self.query
        self.notion.update_database_rows.side_effect = self.save
        self.enterContext(patch.object(processor, "NotionClient", return_value=self.notion))
        self.enterContext(patch.object(self.web, "NotionClient", return_value=self.notion))
        self.enterContext(patch.object(processor, "get_env", side_effect=lambda key: key))
        self.enterContext(patch.object(self.web, "get_env", side_effect=lambda key: key))
        self.app = self.web.create_app({"TESTING": True, "DASHBOARD_CACHE_ENABLED": False})
        self.client = self.app.test_client()
        self.runs = self.app.extensions["analysis_runs"]
        self.cache = self.app.extensions["dashboard_cache"]
        self.invalidated = self.enterContext(patch.object(self.cache, "invalidate", wraps=self.cache.invalidate))
        self.addCleanup(self.wait_finished)
        self.addCleanup(self.release.set)

    def query(self, *, data_source_id, **kwargs):
        if data_source_id == self.web.ADVISORIES:
            if not self.release.wait(3):
                raise TimeoutError("Test did not release worker")
            self.assertIsNone(kwargs.get("started_at"))
            self.assertIsNone(kwargs.get("ended_at"))
            return deepcopy(self.advisories)
        return deepcopy(self.packages) if data_source_id == self.web.PACKAGES else []

    def save(self, *, page_id, properties):
        next(row for row in self.packages if row["page_id"] == page_id)["vulnerability"] = properties["vulnerability"]["select"]["name"]

    def wait_finished(self):
        wait_until(lambda: not self.runs.snapshot()["current"] or
                   self.runs.snapshot()["current"]["status"] not in ("queued", "running"))

    def test_start_to_real_comparison_to_saved_results(self):
        self.assertEqual(self.client.post("/api/run", json={}).status_code, 202)
        self.wait_finished()
        state = self.client.get("/api/run-status")
        self.assertEqual(state.headers["Cache-Control"], "no-store")
        run = state.json["current"]
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual((run["advisory_count"], run["package_count"], run["affected_count"], run["unknown_count"], run["updated_count"]), (3, 3, 1, 1, 2))
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(self.notion.update_database_rows.call_count, 2)
        self.notion.client.close.assert_called_once()
        results = self.client.get("/api/results").json["results"]
        self.assertEqual({row["package_name"]: row["vulnerability"] for row in results},
                         {"demo": "critical", "unknown": "unknown", "untouched": "safe"})
        self.invalidated.assert_called_once_with((self.web.PACKAGES,))

    def test_concurrent_clicks_only_start_one_and_status_does_not_query(self):
        self.release.clear()
        response = self.client.post("/api/run", json={})
        run_id = response.json["run"]["id"]
        wait_until(lambda: self.notion.get_database_rows.call_count == 1)
        responses = []
        def click():
            with self.app.test_client() as client:
                responses.append(client.post("/api/run", json={}))
        threads = [threading.Thread(target=click) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        self.assertEqual([response.status_code for response in responses], [409] * 8)
        self.assertTrue(all(response.json["run"]["id"] == run_id for response in responses))
        for _ in range(3):
            self.assertEqual(self.client.get("/api/run-status").json["current"]["status"], "running")
        self.assertEqual(self.notion.get_database_rows.call_count, 1)
        self.assertEqual(self.client.get("/run-status").status_code, 200)

    def test_partial_save_failure_retains_count_and_invalidates_cache(self):
        self.notion.update_database_rows.side_effect = [None, RuntimeError("secret upstream token")]
        self.client.post("/api/run", json={})
        self.wait_finished()
        response = self.client.get("/api/run-status")
        run = response.json["current"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual((run["updated_count"], run["total_updates"]), (1, 2))
        self.assertNotIn("secret upstream", response.text)
        self.invalidated.assert_called_once()
        self.notion.client.close.assert_called_once()

    def test_query_failure_has_no_writes_and_allows_next_attempt(self):
        self.notion.get_database_rows.side_effect = RuntimeError("unavailable")
        self.client.post("/api/run", json={})
        self.wait_finished()
        self.assertEqual(self.runs.snapshot()["current"]["status"], "failed")
        self.notion.update_database_rows.assert_not_called()
        self.notion.get_database_rows.side_effect = self.query
        self.assertEqual(self.client.post("/api/run", json={}).status_code, 202)
        self.wait_finished()
        self.assertEqual([row["status"] for row in self.runs.snapshot()["history"]], ["succeeded", "failed"])

    def test_input_cannot_change_scope_or_submit_from_other_site(self):
        for kwargs, expected in [({}, 415), ({"json": {"started_at": "2026-09-01"}}, 400),
                                 ({"json": []}, 400),
                                 ({"data": "not-json", "content_type": "application/json"}, 400),
                                 ({"json": {}, "headers": {"Origin": "https://other.example"}}, 403)]:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.client.post("/api/run", **kwargs).status_code, expected)
        self.assertEqual(self.client.post("/api/run?started_at=2026-09-01", json={}).status_code, 400)
        self.assertEqual(self.client.get("/api/run").status_code, 405)
        self.notion.get_database_rows.assert_not_called()
        self.assertIsNone(self.runs.snapshot()["current"])

    def test_result_cache_is_refetched_after_analysis(self):
        self.app.config["DASHBOARD_CACHE_ENABLED"] = True
        self.cache.ensure((self.web.SERVICES, self.web.PACKAGES))
        wait_until(lambda: not self.cache.status((self.web.SERVICES, self.web.PACKAGES))["refreshing"])
        self.assertEqual(self.client.get("/api/results").json["affected_count"], 0)
        self.client.post("/api/run", json={})
        self.wait_finished()
        self.client.get("/api/results")
        wait_until(lambda: not self.cache.status((self.web.PACKAGES,))["refreshing"])
        response = self.client.get("/api/results")
        self.assertEqual(response.json["affected_count"], 1)
        self.assertEqual(response.json["unknown_count"], 1)

    def test_worker_start_failure_is_reported_as_json(self):
        with patch("source.web.analysis_runs.threading.Thread.start", side_effect=RuntimeError("no worker")):
            response = self.client.post("/api/run", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["status"], "error")
        self.assertEqual(self.runs.snapshot()["current"]["status"], "failed")
        self.notion.get_database_rows.assert_not_called()


class AnalysisCacheRaceTests(unittest.TestCase):
    def test_notion_saves_use_shared_request_policy(self):
        client = object.__new__(NotionClient)
        client.client = Mock()
        client.query_policy = Mock()
        client.query_policy.call.side_effect = lambda fn, **kwargs: fn(**kwargs)
        values = {"vulnerability": {"select": {"name": "unknown"}}}
        client.update_database_rows("package", values)
        client.query_policy.call.assert_called_once_with(client.client.pages.update, page_id="package", properties=values)
        client.client.pages.update.assert_called_once_with(page_id="package", properties=values)

    def test_pre_save_fetch_cannot_replace_post_save_results(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def loader(key):
            calls.append(key)
            if len(calls) == 1:
                started.set()
                release.wait(3)
                return [{"vulnerability": "safe"}]
            return [{"vulnerability": "critical"}]
        cache = DashboardDataCache(loader)
        try:
            cache.ensure(("packages",))
            self.assertTrue(started.wait(1))
            cache.invalidate(("packages",))
        finally:
            release.set()
        wait_until(lambda: cache.status(("packages",))["ready"])
        self.assertEqual(cache.read("packages"), [{"vulnerability": "critical"}])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
