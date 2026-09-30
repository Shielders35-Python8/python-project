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
        self.client = self.web.create_app({"DASHBOARD_CACHE_ENABLED": False}).test_client()

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

    def test_dashboard_counts_and_results_table_use_saved_values(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="관리 서비스 2개">2</p>', response.text)
        self.assertIn('aria-label="취약 상태로 저장된 패키지 4개">4</p>', response.text)
        self.assertNotIn('id="results-heading"', response.text)
        self.assertEqual(self.rows.call_count, 3)
        response = self.client.get("/results")
        self.assertIn("저장된 패키지 6개 · 취약 상태 4개 · safe 1개", response.text)
        self.assertIn("SVC-001", response.text)
        self.assertIn("web-gateway", response.text)
        self.assertIn("safe는 등록 시 기본값", response.text)
        self.assertNotIn("취약 범위 밖", response.text)
        self.assertNotIn("취약 범위 포함", response.text)
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
        self.assertIn("등록된 서비스 패키지가 없습니다.", self.client.get("/results").text)
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

    def test_explicit_unknown_is_labeled_and_filtered_without_becoming_safe(self):
        self.data["packages"] = [self.package(1, "unknown"), self.package(2, "safe")]
        data = self.client.get("/api/results?severity=unknown").get_json()
        self.assertEqual((data["affected_count"], data["safe_count"], data["unknown_count"]), (0, 1, 1))
        self.assertEqual(data["filtered_count"], 1)
        self.assertEqual(data["results"][0]["vulnerability"], "unknown")
        self.assertEqual(data["results"][0]["vulnerability_label"], "알 수 없음")
        page = self.client.get("/results?severity=unknown")
        self.assertIn('class="result-badge is-pending">알 수 없음</span>', page.text)
        self.assertIn("package-001", page.text)
        self.assertNotIn("package-002", page.text)

    def test_package_query_failure_is_distinct_from_no_findings(self):
        self.fail_sources.add("packages")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/")
            results_page = self.client.get("/results")
            api = self.client.get("/api/results")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="관리 서비스 2개">2</p>', response.text)
        self.assertIn('aria-label="패키지 취약도 조회 실패">—</p>', response.text)
        self.assertIn("패키지 취약도를 불러오지 못했습니다.", results_page.text)
        self.assertNotIn("등록된 서비스 패키지가 없습니다.", response.text)
        self.assertNotIn("private upstream details", response.text)
        self.assertEqual(api.status_code, 503)
        self.assertIsNone(api.get_json()["affected_count"])
        self.assertEqual(api.get_json()["status"], "error")

    def test_service_query_failure_preserves_package_results(self):
        self.fail_sources.add("services")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/")
            results_page = self.client.get("/results")
            api = self.client.get("/api/results")
        self.assertIn('aria-label="관리 서비스 조회 실패">—</p>', response.text)
        self.assertIn('aria-label="취약 상태로 저장된 패키지 4개">4</p>', response.text)
        self.assertIn("일부 서비스명이 표시되지 않습니다.", results_page.text)
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
        response = self.client.get("/results")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)
        self.assertIn("&lt;b&gt;service&lt;/b&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)

    def test_each_severity_filters_html_and_api_without_changing_total_counts(self):
        for severity, number in (("critical", 2), ("high", 3), ("medium", 4),
                                 ("low", 5), ("safe", 1), ("unknown", 6)):
            with self.subTest(severity=severity):
                response = self.client.get("/results", query_string={"severity": severity})
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"package-{number:03}", response.text)
                for other in set(range(1, 7)) - {number}:
                    self.assertNotIn(f"package-{other:03}", response.text)
                self.assertIn("1개 표시 / 저장된 패키지 6개", response.text)
                data = self.client.get("/api/results", query_string={"severity": severity}).get_json()
                self.assertEqual(data["severity"], severity)
                self.assertEqual((data["package_count"], data["affected_count"], data["filtered_count"]), (6, 4, 1))
                self.assertEqual([row["package_id"] for row in data["results"]], [f"PKG-{number:03}"])
                self.assertEqual(data["severity_counts"]["all"], 6)
                self.assertEqual(data["severity_counts"][severity], 1)
        self.notion.return_value.create_database_row.assert_not_called()
        self.notion.return_value.update_database_rows.assert_not_called()

    def test_unknown_filter_includes_blank_and_unrecognized_saved_values(self):
        self.data["packages"] = [self.package(1, None), self.package(2, ""),
                                 self.package(3, "review"), self.package(4, "all"),
                                 self.package(5, "safe")]
        data = self.client.get("/api/results?severity=unknown").get_json()
        self.assertEqual(data["filtered_count"], 4)
        self.assertEqual({row["package_id"] for row in data["results"]},
                         {"PKG-001", "PKG-002", "PKG-003", "PKG-004"})
        self.assertEqual(data["severity_counts"]["safe"], 1)

    def test_filter_normalizes_saved_values_and_query_and_invalid_query_shows_all(self):
        self.data["packages"] = [self.package(1, " HIGH "), self.package(2, "safe")]
        data = self.client.get("/api/results", query_string={"severity": " HIGH "}).get_json()
        self.assertEqual(data["severity"], "high")
        self.assertEqual(data["filtered_count"], 1)
        self.assertEqual(data["results"][0]["package_id"], "PKG-001")
        for value in ("all", "", "invalid"):
            with self.subTest(value=value):
                response = self.client.get("/results", query_string={"severity": value})
                self.assertIn("package-001", response.text)
                self.assertIn("package-002", response.text)
                self.assertIn('aria-current="true">전체 <span>2</span>', response.text)

    def test_filter_applies_before_pagination_and_survives_next_and_refresh(self):
        self.data["packages"] = [self.package(i, "high") for i in range(1, 56)] + [self.package(100, "safe")]
        first = self.client.get("/results?severity=high")
        last = self.client.get("/results?severity=high&page=2")
        self.assertIn("필터 결과 55개 중 1–50개", first.text)
        self.assertIn('href="/results?page=2&amp;severity=high#results"', first.text)
        self.assertIn("필터 결과 55개 중 51–55개", last.text)
        self.assertIn("package-055", last.text)
        self.assertNotIn("package-050", last.text)
        self.assertNotIn("package-100", last.text)
        self.assertIn('href="/results?refresh=1&amp;severity=high&amp;page=2"', last.text)
        self.assertIn('href="/results?severity=safe"', last.text)
        self.assertIn('href="/results">전체 <span>56</span>', last.text)
        clamped = self.client.get("/results?severity=safe&page=999")
        self.assertIn("package-100", clamped.text)
        self.assertIn("1개 표시 / 저장된 패키지 56개", clamped.text)

    def test_no_matching_results_are_distinct_from_empty_database_and_query_failure(self):
        self.data["packages"] = [self.package(1, "safe")]
        response = self.client.get("/results?severity=critical")
        self.assertIn("선택한 취약도에 해당하는 패키지가 없습니다.", response.text)
        self.assertIn("0개 표시 / 저장된 패키지 1개", response.text)
        self.assertNotIn("등록된 서비스 패키지가 없습니다.", response.text)
        self.assertIn('href="/results">전체 목록 보기</a>', response.text)
        self.data["packages"] = []
        empty = self.client.get("/results?severity=critical")
        self.assertIn("등록된 서비스 패키지가 없습니다.", empty.text)
        self.fail_sources.add("packages")
        with self.assertLogs(self.web.__name__, level="WARNING"):
            failed = self.client.get("/results?severity=critical")
            api = self.client.get("/api/results?severity=critical")
        self.assertIn("패키지 취약도를 불러오지 못했습니다.", failed.text)
        self.assertNotIn("0개 표시", failed.text)
        self.assertNotIn("선택한 취약도에 해당하는 패키지가 없습니다.", failed.text)
        self.assertIsNone(api.get_json()["filtered_count"])
        self.assertIsNone(api.get_json()["severity_counts"])

    def test_main_dashboard_summary_is_not_filtered_by_results_tab_parameter(self):
        response = self.client.get("/?severity=safe")
        self.assertIn('aria-label="취약 상태로 저장된 패키지 4개">4</p>', response.text)
        self.assertIn('aria-label="관리 패키지 6개">6</p>', response.text)
        self.assertNotIn('aria-label="취약도 필터"', response.text)


if __name__ == "__main__":
    unittest.main()
