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
        self.client = self.web.create_app().test_client()

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


if __name__ == "__main__":
    unittest.main()
