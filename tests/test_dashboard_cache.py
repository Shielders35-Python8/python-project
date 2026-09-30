"""캐시의 동시 조회, 실패 보존, 실제 라우트의 빠른 로딩을 외부 요청 없이 검증한다."""

import importlib
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

from source.common.notion.query_policy import NotionQueryPolicy, QueryDeferred
from source.web.data_cache import CacheUnavailable, DashboardDataCache


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("백그라운드 작업이 완료되지 않았습니다.")
        time.sleep(0.005)


class DataCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.release = threading.Event()
        self.loader = Mock(side_effect=lambda key: self.load(key))
        self.cache = DashboardDataCache(self.loader, clock=lambda: self.now)
        self.value = [{"id": "old"}]
        self.error = None
        self.addCleanup(lambda: wait_until(lambda: not self.cache.status(["rows"])["refreshing"]))
        self.addCleanup(self.release.set)

    def load(self, key):
        self.release.wait(3)
        if self.error:
            raise self.error
        return self.value

    def finish(self):
        self.release.set()
        wait_until(lambda: not self.cache.status(["rows"])["refreshing"])

    def test_concurrent_cold_reads_start_one_job_and_do_not_wait(self):
        threads = [threading.Thread(target=self.cache.ensure, args=(["rows"],)) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
        self.assertTrue(self.cache.status(["rows"])["loading"])
        self.assertEqual(self.loader.call_count, 1)
        with self.assertRaises(CacheUnavailable):
            self.cache.read("rows")
        self.finish()
        self.assertEqual(self.cache.read("rows"), [{"id": "old"}])

    def test_stale_snapshot_survives_refresh_failure_and_backoff(self):
        self.cache.ensure(["rows"])
        self.finish()
        self.now += 61
        self.release.clear()
        self.error = RuntimeError("private upstream detail")
        state = self.cache.ensure(["rows"])
        self.assertTrue(state["stale"])
        self.assertTrue(state["refreshing"])
        self.assertEqual(self.cache.read("rows"), [{"id": "old"}])
        with self.assertLogs("source.web.data_cache", level="WARNING"):
            self.finish()
        self.assertTrue(self.cache.status(["rows"])["failed"])
        for _ in range(5):
            self.cache.ensure(["rows"], force=True)
        self.assertEqual(self.loader.call_count, 2)
        self.now += 31
        self.error = None
        self.value = [{"id": "new"}]
        self.cache.ensure(["rows"])
        self.finish()
        self.assertEqual(self.cache.read("rows"), self.value)
        self.assertFalse(self.cache.status(["rows"])["failed"])

    def test_empty_success_is_cached_and_manual_refresh_is_coalesced(self):
        self.value = []
        self.cache.ensure(["rows"])
        self.finish()
        for _ in range(10):
            self.cache.ensure(["rows"], force=True)
        self.assertEqual(self.loader.call_count, 1)
        self.assertEqual(self.cache.read("rows"), [])
        self.assertTrue(self.cache.status(["rows"])["ready"])
        self.now += 6
        self.cache.ensure(["rows"], force=True)
        self.finish()
        self.assertEqual(self.loader.call_count, 2)

    def test_cold_failure_obeys_long_retry_after_even_with_manual_refresh(self):
        self.error = HTTPResponseError(httpx.Response(429, headers={"Retry-After": "120"}))
        self.cache.ensure(["rows"])
        with self.assertLogs("source.web.data_cache", level="WARNING"):
            self.finish()
        self.now += 60
        self.cache.ensure(["rows"], force=True)
        self.assertEqual(self.loader.call_count, 1)
        self.assertTrue(self.cache.status(["rows"])["failed"])
        self.assertFalse(self.cache.status(["rows"])["loading"])


class QueryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sleeps = []
        self.policy = NotionQueryPolicy(clock=lambda: self.now, sleep=self.sleep)

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay

    def test_rate_limit_retries_same_cursor_after_server_delay(self):
        error = HTTPResponseError(httpx.Response(429, headers={"Retry-After": "4"}))
        query = Mock(side_effect=[error, {"results": []}])
        result = self.policy.call(query, start_cursor="page-2")
        self.assertEqual(result, {"results": []})
        self.assertEqual(self.sleeps, [4])
        self.assertEqual(query.call_args_list[0], query.call_args_list[1])
        self.policy.call(Mock(return_value={}))
        self.assertEqual(self.sleeps[-1], 0.5)

    def test_timeout_retries_are_bounded_and_auth_errors_are_not_retried(self):
        query = Mock(side_effect=RequestTimeoutError())
        with self.assertRaises(RequestTimeoutError):
            self.policy.call(query)
        self.assertEqual(query.call_count, 3)
        query = Mock(side_effect=HTTPResponseError(httpx.Response(401)))
        with self.assertRaises(HTTPResponseError):
            self.policy.call(query)
        self.assertEqual(query.call_count, 1)

    def test_long_server_cooldown_is_shared_without_sleeping_worker(self):
        error = HTTPResponseError(httpx.Response(429, headers={"Retry-After": "120"}))
        with self.assertRaises(HTTPResponseError):
            self.policy.call(Mock(side_effect=error))
        other_query = Mock()
        with self.assertRaises(QueryDeferred):
            self.policy.call(other_query)
        other_query.assert_not_called()
        self.assertEqual(self.sleeps, [])

    def test_access_restriction_is_not_retried(self):
        error = APIResponseError(httpx.Response(429), "restricted", "rate_limited",
                                 {"rate_limit_reason": "public_api_request_blocked"})
        query = Mock(side_effect=error)
        with self.assertRaises(APIResponseError):
            self.policy.call(query)
        self.assertEqual(query.call_count, 1)

    def test_notion_pagination_retries_failed_page_without_losing_rows(self):
        from source.common.notion.notion import NotionClient
        client = object.__new__(NotionClient)
        client.client = Mock()
        client.query_policy = self.policy
        query = client.client.data_sources.query
        query.side_effect = [
            {"results": [{"id": "p1", "properties": {}}], "has_more": True, "next_cursor": "cursor-2"},
            HTTPResponseError(httpx.Response(429, headers={"Retry-After": "2"})),
            {"results": [{"id": "p2", "properties": {}}], "has_more": False, "next_cursor": None},
        ]
        self.assertEqual(client.get_database_rows("source"), [{"page_id": "p1"}, {"page_id": "p2"}])
        self.assertEqual(query.call_args_list[1].kwargs["start_cursor"], "cursor-2")
        self.assertEqual(query.call_args_list[1], query.call_args_list[2])


class CachedDashboardRoutesTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("source.common.slack.notifications.send_error_message", return_value=False))
        self.web = importlib.import_module("source.web.app")
        self.release = threading.Event()
        self.calls = []
        self.fail_sources = set()
        self.now = 10
        self.data = {
            self.web.ADVISORIES: [{"id": "GHSA-one", "title": "Cached notice", "page_id": "a",
                                   "severity": "high", "published_at": "2026-09-01"}],
            self.web.SERVICES: [{"page_id": "s", "resource_name": "Cached service"}],
            self.web.PACKAGES: [{"page_id": "p", "package_name": "Cached package", "vulnerability": "high",
                                "service_id": ["s"]}],
        }
        self.enterContext(patch.object(self.web, "fetch_saved_rows", side_effect=self.load))
        self.app = self.web.create_app()
        self.client = self.app.test_client()
        self.cache = self.app.extensions["dashboard_cache"]
        self.cache.clock = lambda: self.now
        self.addCleanup(lambda: wait_until(lambda: not self.cache.status(self.data)["refreshing"]))
        self.addCleanup(self.release.set)

    def load(self, key, policy):
        self.calls.append(key)
        self.release.wait(3)
        if key in self.fail_sources:
            raise RuntimeError("private upstream details")
        return self.data[key]

    def warm(self):
        self.client.get("/")
        self.release.set()
        wait_until(lambda: self.cache.status(self.data)["ready"])

    def test_cold_html_and_api_return_loading_without_blocking_navigation(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("데이터를 불러오는 중입니다.", response.text)
        self.assertIn('href="/results"', response.text)
        self.assertNotIn("조회 실패", response.text)
        api = self.client.get("/api/results")
        self.assertEqual(api.status_code, 202)
        self.assertEqual(api.get_json()["status"], "loading")
        self.assertEqual(api.headers["Retry-After"], "2")
        for _ in range(3):
            self.client.get("/api/cache-status?view=dashboard")
        wait_until(lambda: len(self.calls) == 3)
        self.assertCountEqual(self.calls, self.data)
        self.warm()
        self.assertIn("Cached package", self.client.get("/").text)

    def test_tabs_filters_and_pagination_share_one_snapshot(self):
        self.warm()
        for path in ("/", "/results", "/results?severity=high&page=2", "/advisories/list",
                     "/advisories/list?page=2", "/advisories?started_at=2026-09-01",
                     "/api/results?severity=high", "/api/advisories", "/api/advisories/analysis"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertCountEqual(self.calls, self.data)
        result = self.client.get("/api/results?severity=high").get_json()
        self.assertEqual(result["filtered_count"], 1)
        self.assertTrue(result["cache"]["ready"])

    def test_expired_data_renders_while_background_refresh_is_pending(self):
        self.warm()
        self.now += 61
        self.release.clear()
        response = self.client.get("/results?severity=high&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Cached package", response.text)
        self.assertIn("기존 데이터를 먼저 표시합니다.", response.text)
        self.assertIn("refresh=1", response.text)
        self.assertIn("severity=high", response.text)
        self.assertTrue(self.client.get("/api/cache-status?view=results").get_json()["refreshing"])

    def test_invalid_dates_health_and_status_do_not_start_notion_queries(self):
        self.assertEqual(self.client.get("/advisories?started_at=bad-date").status_code, 400)
        self.assertEqual(self.client.get("/api/cache-status?view=invalid").status_code, 400)
        self.client.get("/api/cache-status")
        self.client.get("/api/health")
        self.client.get("/run-status")
        self.assertEqual(self.calls, [])

    def test_app_instances_do_not_share_private_data(self):
        self.warm()
        other = self.web.create_app()
        self.assertFalse(other.extensions["dashboard_cache"].status(self.data)["ready"])

    def test_failed_refresh_keeps_real_results_and_reports_staleness(self):
        self.warm()
        self.fail_sources.add(self.web.PACKAGES)
        self.now += 61
        with self.assertLogs("source.web.data_cache", level="WARNING"):
            self.client.get("/results")
            wait_until(lambda: not self.cache.status(self.web.PAGE_SOURCES["results"])["refreshing"])
        response = self.client.get("/api/results")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["package_count"], 1)
        self.assertTrue(response.get_json()["cache"]["failed"])
        html = self.client.get("/results").text
        self.assertIn("최신 데이터를 가져오지 못했습니다.", html)
        self.assertIn("Cached package", html)
        self.assertNotIn("private upstream details", html)

    def test_cold_failure_is_not_reported_as_empty_and_does_not_retry_on_every_request(self):
        self.fail_sources.add(self.web.ADVISORIES)
        self.client.get("/advisories/list")
        with self.assertLogs("source.web.data_cache", level="WARNING"):
            self.release.set()
            wait_until(lambda: not self.cache.status([self.web.ADVISORIES])["refreshing"])
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/api/advisories")
            html = self.client.get("/advisories/list?refresh=1").text
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(response.get_json()["advisory_count"])
        self.assertIn("보안 공지를 불러오지 못했습니다.", html)
        self.assertNotIn("Notion에 저장된 공지가 없습니다.", html)
        self.assertEqual(self.calls, [self.web.ADVISORIES])

    def test_unrecognized_query_keys_are_not_passed_to_url_builder(self):
        self.warm()
        response = self.client.get("/results?endpoint=bad&_external=true&_scheme=https&severity=high")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/results?severity=high&amp;refresh=1"', response.text)
        self.assertNotIn("https://", response.text)


if __name__ == "__main__":
    unittest.main()
