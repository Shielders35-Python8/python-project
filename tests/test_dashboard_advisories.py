"""대시보드의 저장 공지 집계와 조회 실패 표시를 외부 요청 없이 검증한다."""

import importlib
import unittest
from unittest.mock import patch


class DashboardAdvisoriesTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch(
            "source.common.slack.notifications.send_error_message", return_value=False,
        ))
        self.web = importlib.import_module("source.web.app")
        self.notion = self.enterContext(patch.object(self.web, "NotionClient"))
        self.env = self.enterContext(patch.object(
            self.web, "get_env", side_effect={
                "NOTION_ADVISORIES_DATA_SOURCE_ID": "advisories-data-source",
                "NOTION_SERVICE_DATA_SOURCE_ID": "services-data-source",
                "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID": "packages-data-source",
            }.__getitem__,
        ))
        self.rows = self.notion.return_value.get_database_rows
        self.advisories = []
        self.rows.side_effect = lambda *, data_source_id: (
            self.advisories if data_source_id == "advisories-data-source" else []
        )
        self.client = self.web.create_app({"DASHBOARD_CACHE_ENABLED": False}).test_client()

    def test_counts_distinct_notices_across_package_rows(self):
        self.advisories = [
            {"id": "GHSA-one", "page_id": "page-1", "package_name": "package-a"},
            {"id": "GHSA-one", "page_id": "page-2", "package_name": "package-b"},
            {"id": "GHSA-two", "page_id": "page-3"},
        ]
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="수집한 보안 공지 2건">2</p>', response.text)
        self.assertIn("Notion 저장 공지 · 중복 제외", response.text)
        self.env.assert_any_call("NOTION_ADVISORIES_DATA_SOURCE_ID")
        self.rows.assert_any_call(data_source_id="advisories-data-source")
        self.assertEqual(sum(call.kwargs["data_source_id"] == "advisories-data-source"
                             for call in self.rows.call_args_list), 1)
        self.notion.return_value.create_database_row.assert_not_called()
        self.notion.return_value.update_database_rows.assert_not_called()

    def test_empty_database_shows_zero(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="수집한 보안 공지 0건">0</p>', response.text)
        self.assertIn("Notion에 저장된 공지가 없습니다.", response.text)

    def test_rows_without_ids_are_not_merged(self):
        self.advisories = [
            {"id": "", "page_id": "page-1"},
            {"id": None, "page_id": "page-2"},
        ]
        self.assertIn('aria-label="수집한 보안 공지 2건">2</p>', self.client.get("/").text)

    def test_query_failure_does_not_look_like_empty_database(self):
        self.rows.side_effect = RuntimeError("private upstream error details")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="보안 공지 조회 실패">—</p>', response.text)
        self.assertIn("Notion 공지 조회 실패", response.text)
        self.assertNotIn("private upstream error details", response.text)
        self.assertNotIn("Notion에 저장된 공지가 없습니다.", response.text)

    def test_missing_configuration_keeps_dashboard_available(self):
        for missing_value in (None, " "):
            with self.subTest(value=missing_value):
                self.env.side_effect = KeyError("missing setting") if missing_value is None else None
                self.env.return_value = missing_value
                with self.assertLogs(self.web.__name__, level="WARNING"):
                    response = self.client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Notion 공지 조회 실패", response.text)
        self.notion.assert_not_called()

    def test_run_status_and_health_do_not_query_notion(self):
        for path in ("/run-status", "/api/health"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.notion.assert_not_called()

    def test_refresh_reads_current_saved_notices(self):
        self.assertIn('aria-label="수집한 보안 공지 0건">0</p>', self.client.get("/").text)
        self.advisories = [{"id": "GHSA-new", "page_id": "page-new"}]
        self.assertIn('aria-label="수집한 보안 공지 1건">1</p>', self.client.get("/").text)
        self.assertEqual(sum(call.kwargs["data_source_id"] == "advisories-data-source"
                             for call in self.rows.call_args_list), 2)

    @staticmethod
    def notice(identifier, **values):
        return {
            "id": identifier, "page_id": f"page-{identifier}",
            "title": f"Notice {identifier}", "severity": "high",
            "url": f"https://github.com/advisories/{identifier}",
            "published_at": "2026-09-01T00:00:00Z", "updated_at": None,
            "package_name": "example-package", "ecosystem": "npm",
            "package_version_range": ">= 1.0.0, < 2.0.0", **values,
        }

    def test_notice_tab_and_source_link_show_saved_fields(self):
        self.advisories = [self.notice("GHSA-ONE", cve_id="CVE-2026-12345")]
        response = self.client.get("/advisories/list")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-current="page">보안 공지</a>', response.text)
        self.assertEqual(response.text.count('aria-current="page"'), 1)
        for value in ("Notice GHSA-ONE", "CVE-2026-12345", "high", "example-package", "npm", "2026-09-01"):
            self.assertIn(value, response.text)
        self.assertIn('href="https://github.com/advisories/GHSA-ONE" target="_blank" rel="noopener noreferrer"', response.text)
        self.assertIn('href="/advisories/list"', response.text)
        self.rows.assert_called_once_with(data_source_id="advisories-data-source")
        self.notion.return_value.create_database_row.assert_not_called()
        self.notion.return_value.update_database_rows.assert_not_called()

    def test_list_groups_notices_but_retains_all_package_ranges(self):
        self.advisories = [
            self.notice("GHSA-ONE", page_id="a", package_version_range="< 1.0.0"),
            self.notice("ghsa-one", page_id="b", package_version_range=">= 2.0.0, < 3.0.0"),
            self.notice("GHSA-ONE", page_id="c", package_name="another-package"),
            self.notice("GHSA-ONE", page_id="d", package_name="another-package"),
        ]
        data = self.client.get("/api/advisories").get_json()
        self.assertEqual((data["advisory_count"], data["advisory_row_count"]), (1, 4))
        self.assertEqual(len(data["advisories"][0]["packages"]), 3)
        response = self.client.get("/advisories/list")
        self.assertIn("&lt; 1.0.0", response.text)
        self.assertIn("&gt;= 2.0.0, &lt; 3.0.0", response.text)
        self.assertIn("another-package", response.text)

    def test_list_orders_by_publication_time_and_handles_missing_dates(self):
        self.advisories = [
            self.notice("GHSA-OLD", published_at="2026-09-01T00:00:00Z"),
            self.notice("GHSA-LOCAL", published_at="2026-09-02T01:00:00+09:00"),
            self.notice("GHSA-NEW", published_at="2026-09-01T23:00:00Z"),
            self.notice("GHSA-UNDATED", published_at="invalid-date"),
        ]
        data = self.client.get("/api/advisories").get_json()
        self.assertEqual([row["id"] for row in data["advisories"]],
                         ["GHSA-NEW", "GHSA-LOCAL", "GHSA-OLD", "GHSA-UNDATED"])
        self.assertEqual(data["advisories"][1]["published_date"], "2026-09-01")
        self.assertIsNone(data["advisories"][-1]["published_date"])

    def test_empty_notice_list_is_successful_and_distinct_from_failure(self):
        response = self.client.get("/advisories/list")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Notion에 저장된 공지가 없습니다.", response.text)
        data = self.client.get("/api/advisories").get_json()
        self.assertEqual((data["status"], data["source"], data["advisory_count"]), ("ok", "notion", 0))
        self.assertEqual(data["advisories"], [])
        self.rows.side_effect = RuntimeError("private token details")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            failed_page = self.client.get("/advisories/list")
            failed_api = self.client.get("/api/advisories")
        self.assertIn("보안 공지를 불러오지 못했습니다.", failed_page.text)
        self.assertNotIn("Notion에 저장된 공지가 없습니다.", failed_page.text)
        self.assertNotIn("private token details", failed_page.text)
        self.assertEqual(failed_api.status_code, 503)
        self.assertIsNone(failed_api.get_json()["advisory_count"])

    def test_notice_pagination_does_not_drop_last_page(self):
        self.advisories = [self.notice(f"GHSA-{number:03}") for number in range(1, 56)]
        first = self.client.get("/advisories/list")
        last = self.client.get("/advisories/list?page=2")
        self.assertIn("전체 55건 중 1–50건", first.text)
        self.assertNotIn("Notice GHSA-005", first.text)
        self.assertIn("전체 55건 중 51–55건", last.text)
        self.assertIn("Notice GHSA-001", last.text)
        self.assertNotIn("Notice GHSA-006", last.text)
        for query, expected in (("-1", "1–50"), ("invalid", "1–50"), ("999", "51–55")):
            self.assertIn(f"전체 55건 중 {expected}건", self.client.get(f"/advisories/list?page={query}").text)

    def test_notice_text_is_escaped_and_unsafe_urls_are_not_links(self):
        self.advisories = [self.notice("GHSA-ONE", title="<script>alert(1)</script>", url="javascript:alert(1)")]
        response = self.client.get("/advisories/list")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertNotIn("javascript:", response.text)
        self.assertNotIn('class="advisory-source"', response.text)

    def test_missing_fields_and_ids_do_not_merge_unrelated_notices(self):
        self.advisories = [{"page_id": "page-1"}, {"page_id": "page-2"}]
        data = self.client.get("/api/advisories").get_json()
        self.assertEqual(data["advisory_count"], 2)
        response = self.client.get("/advisories/list")
        self.assertIn("제목 미설정", response.text)
        self.assertIn("패키지 정보가 없습니다.", response.text)

    def test_refresh_of_notice_list_reads_current_database_rows(self):
        self.assertIn("Notion에 저장된 공지가 없습니다.", self.client.get("/advisories/list").text)
        self.advisories = [self.notice("GHSA-NEW")]
        response = self.client.get("/advisories/list")
        self.assertIn("Notice GHSA-NEW", response.text)
        self.assertNotIn("Notion에 저장된 공지가 없습니다.", response.text)


if __name__ == "__main__":
    unittest.main()
