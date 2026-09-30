"""실제 저장값 조회, 서비스 관계, 집계 및 페이지 이동을 외부 요청 없이 검증한다."""

import importlib
import unittest
from unittest.mock import patch


class DashboardResultsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch(
            "source.common.slack.notifications.send_error_message", return_value=False,
        ))
        self.web = importlib.import_module("source.web.app")
        self.notion = self.enterContext(patch.object(self.web, "NotionClient"))
        self.enterContext(patch.object(self.web, "get_env", side_effect={
            "NOTION_ADVISORIES_DATA_SOURCE_ID": "advisories",
            "NOTION_SERVICE_DATA_SOURCE_ID": "services",
            "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID": "packages",
        }.__getitem__))
        self.data = {
            "advisories": [],
            "services": [
                {"id": "SVC-001", "resource_name": "web-gateway", "page_id": "service-1"},
                {"id": "SVC-002", "resource_name": "order-service", "page_id": "service-2"},
            ],
            "packages": [
                self.package(1, "safe"), self.package(2, "critical"),
                self.package(3, "high"), self.package(4, "medium"),
                self.package(5, "low"), self.package(6, None),
            ],
        }
        self.fail_sources = set()
        self.rows = self.notion.return_value.get_database_rows
        self.rows.side_effect = self.query
        self.client = self.web.create_app().test_client()

    @staticmethod
    def package(number, vulnerability):
        return {
            "id": f"PKG-{number:03}", "page_id": f"package-{number}",
            "service_id": ["service-1"], "package_name": f"package-{number:03}",
            "package_version": "1.2.3", "ecosystem": "npm", "vulnerability": vulnerability,
        }

    def query(self, *, data_source_id):
        if data_source_id in self.fail_sources:
            raise RuntimeError("private upstream details")
        return self.data[data_source_id]

    def test_dashboard_counts_and_table_use_saved_values(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="관리 서비스 2개">2</p>', response.text)
        self.assertIn('aria-label="취약 상태로 저장된 패키지 4개">4</p>', response.text)
        self.assertIn("저장된 패키지 6개 · 취약 상태 4개 · safe 1개", response.text)
        self.assertIn("SVC-001", response.text)
        self.assertIn("web-gateway", response.text)
        self.assertIn("safe는 등록 시 기본값", response.text)
        self.assertNotIn("취약 범위 밖", response.text)
        self.assertNotIn("취약 범위 포함", response.text)
        self.assertEqual(self.rows.call_count, 3)
        self.notion.return_value.create_database_row.assert_not_called()
        self.notion.return_value.update_database_rows.assert_not_called()

    def test_results_page_and_api_do_not_collect_or_fetch_advisories(self):
        response = self.client.get("/results")
        self.assertEqual(response.status_code, 200)
        self.assertIn("package-002", response.text)
        data = self.client.get("/api/results").get_json()
        self.assertEqual((data["status"], data["source"]), ("ok", "notion"))
        self.assertEqual(data["result_type"], "saved_package_vulnerability")
        self.assertEqual([row["vulnerability"] for row in data["results"]],
                         ["critical", "high", "medium", "low", None, "safe"])
        self.assertEqual(data["affected_count"], 4)
        self.assertEqual(data["package_count"], 6)
        self.assertTrue(all(call.kwargs["data_source_id"] != "advisories"
                            for call in self.rows.call_args_list))

    def test_empty_databases_show_zero_without_failure(self):
        self.data.update(services=[], packages=[])
        response = self.client.get("/")
        self.assertIn('aria-label="관리 서비스 0개">0</p>', response.text)
        self.assertIn('aria-label="취약 상태로 저장된 패키지 0개">0</p>', response.text)
        self.assertIn("등록된 서비스 패키지가 없습니다.", response.text)
        self.assertNotIn("조회 실패", response.text)

    def test_relations_do_not_duplicate_package_counts_or_drop_orphans(self):
        self.data["packages"] = [self.package(1, "high"), self.package(2, "safe"), self.package(3, None)]
        self.data["packages"][0]["service_id"] = ["service-1", "service-2"]
        self.data["packages"][1]["service_id"] = []
        self.data["packages"][2]["service_id"] = ["removed-service"]
        data = self.client.get("/api/results").get_json()
        self.assertEqual(data["package_count"], 3)
        self.assertEqual(data["affected_count"], 1)
        self.assertEqual([service["id"] for service in data["results"][0]["services"]],
                         ["SVC-001", "SVC-002"])
        response = self.client.get("/results")
        self.assertIn("서비스 미연결", response.text)
        self.assertIn("서비스 확인 필요", response.text)

    def test_unknown_saved_status_is_not_classified_as_safe(self):
        self.data["packages"] = [self.package(1, "review"), self.package(2, "")]
        data = self.client.get("/api/results").get_json()
        self.assertEqual((data["affected_count"], data["safe_count"], data["unknown_count"]), (0, 0, 2))

    def test_package_query_failure_is_distinct_from_no_findings(self):
        self.fail_sources.add("packages")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/")
            api = self.client.get("/api/results")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="관리 서비스 2개">2</p>', response.text)
        self.assertIn('aria-label="패키지 취약도 조회 실패">—</p>', response.text)
        self.assertIn("패키지 취약도를 불러오지 못했습니다.", response.text)
        self.assertNotIn("등록된 서비스 패키지가 없습니다.", response.text)
        self.assertNotIn("private upstream details", response.text)
        self.assertEqual(api.status_code, 503)
        self.assertIsNone(api.get_json()["affected_count"])
        self.assertEqual(api.get_json()["status"], "error")

    def test_service_query_failure_preserves_package_results(self):
        self.fail_sources.add("services")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/")
            api = self.client.get("/api/results")
        self.assertIn('aria-label="관리 서비스 조회 실패">—</p>', response.text)
        self.assertIn('aria-label="취약 상태로 저장된 패키지 4개">4</p>', response.text)
        self.assertIn("일부 서비스명이 표시되지 않습니다.", response.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.get_json()["status"], "partial")

    def test_pagination_keeps_total_count_and_covers_last_page(self):
        self.data["packages"] = [self.package(i, "safe") for i in range(1, 56)]
        first = self.client.get("/results")
        last = self.client.get("/results?page=2")
        self.assertIn("전체 55개 중 1–50개", first.text)
        self.assertIn("package-050", first.text)
        self.assertNotIn("package-051", first.text)
        self.assertIn("전체 55개 중 51–55개", last.text)
        self.assertIn("package-055", last.text)
        self.assertNotIn("package-050", last.text)
        for query, expected in (("-1", "1–50"), ("abc", "1–50"), ("999", "51–55")):
            with self.subTest(query=query):
                self.assertIn(f"전체 55개 중 {expected}개", self.client.get(f"/results?page={query}").text)

    def test_refresh_reflects_saved_status_and_escapes_database_text(self):
        self.data["packages"] = [self.package(1, "safe")]
        self.assertEqual(self.client.get("/api/results").get_json()["affected_count"], 0)
        self.data["packages"][0].update(vulnerability="high", package_name="<script>alert(1)</script>")
        self.data["services"][0]["resource_name"] = "<b>service</b>"
        response = self.client.get("/")
        self.assertIn('aria-label="취약 상태로 저장된 패키지 1개">1</p>', response.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)
        self.assertIn("&lt;b&gt;service&lt;/b&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)


if __name__ == "__main__":
    unittest.main()
