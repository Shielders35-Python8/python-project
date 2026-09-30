"""공지 집계의 중복·날짜 경계와 Notion 대시보드 연동을 검증한다."""

import importlib
import unittest
from unittest.mock import patch

from source.services.advisory_analysis import analyze_advisories


def notice(identifier="GHSA-one", **values):
    return {"id": identifier, "severity": "high", "published_at": "2026-09-01T12:00:00Z",
            "ecosystem": "npm", "package_name": "sample", **values}


class AdvisoryAnalysisTests(unittest.TestCase):
    def test_duplicate_versions_and_packages_do_not_inflate_advisory_counts(self):
        rows = [
            notice(package_version_range="<1"),
            notice(package_version_range=">=2, <3"),
            notice(" ghsa-ONE ", ecosystem=" NPM ", package_name="second"),
            notice("GHSA-two", severity="critical"),
        ]
        data = analyze_advisories(rows)
        self.assertEqual(data["summary"]["advisory_count"], 2)
        self.assertEqual(data["summary"]["row_count"], 4)
        self.assertEqual(data["summary"]["high_risk_count"], 2)
        self.assertEqual(data["summary"]["package_count"], 2)
        self.assertEqual({item["label"]: item["count"] for item in data["ecosystems"]}, {"npm": 2})
        self.assertEqual({item["name"]: item["count"] for item in data["top_packages"]}, {"sample": 2, "second": 1})
        self.assertEqual(sum(item["count"] for item in data["severity"]), 2)
        self.assertEqual(sum(item["count"] for item in data["timeline"]), 2)

    def test_one_advisory_can_belong_to_multiple_ecosystems(self):
        data = analyze_advisories([notice(), notice(ecosystem="pip")])
        self.assertEqual(data["summary"]["advisory_count"], 1)
        self.assertEqual(data["summary"]["ecosystem_count"], 2)
        self.assertEqual(data["summary"]["package_count"], 2)
        self.assertEqual(sum(item["count"] for item in data["ecosystems"]), 2)

    def test_missing_fields_remain_visible_and_missing_ids_use_page_identity(self):
        data = analyze_advisories([
            {"page_id": "same-page"}, {"page_id": "same-page"},
            {"page_id": "other-page", "severity": "unexpected", "published_at": "bad date"},
            {}, {},
        ])
        self.assertEqual(data["summary"]["advisory_count"], 4)
        self.assertEqual(data["summary"]["missing_id_count"], 4)
        self.assertEqual(data["summary"]["undated_count"], 4)
        self.assertEqual(data["summary"]["high_risk_count"], 0)
        self.assertEqual(data["summary"]["ecosystem_count"], 0)
        self.assertEqual(data["severity"][-1]["count"], 4)
        self.assertEqual(data["top_packages"], [])
        self.assertEqual(data["timeline"], [])

    def test_conflicting_rows_use_highest_severity_and_earliest_date(self):
        rows = [notice(severity="low", published_at="2026-09-10"),
                notice(severity=" CRITICAL ", published_at="2026-09-01"),
                notice(severity=None, published_at=None)]
        data = analyze_advisories(rows)
        self.assertEqual(data, analyze_advisories(list(reversed(rows))))
        self.assertEqual(data["severity"][0]["count"], 1)
        self.assertEqual(data["period_start"], "2026-09-01")

    def test_date_filters_are_inclusive_in_utc_and_exclude_undated(self):
        rows = [
            notice("before", published_at="2026-09-01T00:30:00+09:00"),
            notice("first", published_at="2026-09-01T00:00:00Z"),
            notice("last", published_at="2026-09-30T23:59:59Z"),
            notice("after", published_at="2026-10-01"),
            notice("unknown", published_at=None),
        ]
        data = analyze_advisories(rows, started_at="2026-09-01", ended_at="2026-09-30")
        self.assertEqual(data["summary"]["advisory_count"], 2)
        self.assertEqual(data["excluded_undated_count"], 1)
        self.assertEqual(data["total_advisory_count"], 5)
        self.assertEqual(data["period_start"], "2026-09-01")
        self.assertEqual(data["period_end"], "2026-09-30")
        self.assertEqual(analyze_advisories(rows, started_at="2026-10-01")["summary"]["advisory_count"], 1)
        self.assertEqual(analyze_advisories(rows, ended_at="2026-08-31")["summary"]["advisory_count"], 1)

    def test_invalid_date_filters_raise_clear_errors(self):
        for filters in ({"started_at": "2026-02-30"}, {"ended_at": "20260901"},
                        {"started_at": "2026-10-01", "ended_at": "2026-09-01"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                analyze_advisories([], **filters)

    def test_timeline_fills_gaps_and_changes_interval_for_long_periods(self):
        cases = [
            ("2026-09-01", "2026-09-03", "일별", [1, 0, 1]),
            ("2025-12-01", "2026-03-01", "월별", [1, 0, 0, 1]),
            ("2022-01-01", "2026-09-01", "연도별", [1, 0, 0, 0, 1]),
        ]
        for first, last, unit, counts in cases:
            with self.subTest(unit=unit):
                data = analyze_advisories([notice("first", published_at=first), notice("last", published_at=last)])
                self.assertEqual(data["timeline_unit"], unit)
                self.assertEqual([item["count"] for item in data["timeline"]], counts)

    def test_top_packages_are_limited_and_sorted_by_notice_count(self):
        rows = [notice(str(i), package_name=f"pkg-{i:02}") for i in range(12)]
        rows.append(notice("extra", package_name="pkg-11"))
        data = analyze_advisories(rows)
        self.assertEqual(data["summary"]["package_count"], 12)
        self.assertEqual(len(data["top_packages"]), 10)
        self.assertEqual(data["top_packages"][0]["name"], "pkg-11")
        self.assertEqual(data["top_packages"][0]["count"], 2)

    def test_empty_input_has_no_nan_or_division_by_zero(self):
        data = analyze_advisories([])
        self.assertEqual(data["summary"]["advisory_count"], 0)
        self.assertEqual(data["summary"]["high_risk_percent"], 0)
        self.assertTrue(all(item["percent"] == 0 for item in data["severity"]))


class AdvisoryDashboardTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("source.common.slack.notifications.send_error_message", return_value=False))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("No external requests")))
        self.web = importlib.import_module("source.web.app")
        self.env = self.enterContext(patch.object(self.web, "get_env", return_value="advisories-source"))
        self.notion = self.enterContext(patch.object(self.web, "NotionClient"))
        self.rows = self.notion.return_value.get_database_rows
        self.rows.return_value = [notice(), notice(package_name="second")]
        self.client = self.web.create_app().test_client()

    def test_tab_queries_only_advisories_and_renders_all_charts(self):
        response = self.client.get("/advisories")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-current="page">공지 분석</a>', response.text)
        for title in ("심각도 분포", "생태계별 공지", "공지 게시 추이", "공지가 많은 패키지"):
            self.assertIn(title, response.text)
        self.env.assert_called_once_with("NOTION_ADVISORIES_DATA_SOURCE_ID")
        self.rows.assert_called_once_with(data_source_id="advisories-source")
        self.notion.return_value.create_database_row.assert_not_called()
        self.notion.return_value.update_database_rows.assert_not_called()

    def test_api_uses_same_aggregation_and_refreshes_saved_data(self):
        response = self.client.get("/api/advisories/analysis")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["analysis"], analyze_advisories(self.rows.return_value))
        self.rows.return_value.append(notice("new"))
        self.assertEqual(self.client.get("/api/advisories/analysis").json["analysis"]["summary"]["advisory_count"], 2)

    def test_period_filter_applies_to_html_and_api(self):
        query = "?started_at=2026-10-01&ended_at=2026-10-31"
        response = self.client.get("/advisories" + query)
        self.assertEqual(response.status_code, 200)
        self.assertIn("선택한 기간에 해당하는 공지가 없습니다.", response.text)
        self.assertIn('value="2026-10-01"', response.text)
        self.assertEqual(self.client.get("/api/advisories/analysis" + query).json["analysis"]["summary"]["advisory_count"], 0)

    def test_invalid_filters_do_not_call_notion(self):
        for path in ("/advisories", "/api/advisories/analysis"):
            with self.subTest(path=path):
                response = self.client.get(path + "?started_at=bad-date")
                self.assertEqual(response.status_code, 400)
                self.assertIn("올바른 날짜", response.text)
        self.notion.assert_not_called()

    def test_empty_data_and_query_failures_have_different_states(self):
        self.rows.return_value = []
        response = self.client.get("/advisories")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Notion에 저장된 공지가 없습니다.", response.text)
        self.rows.side_effect = RuntimeError("private upstream detail")
        for path in ("/advisories", "/api/advisories/analysis"):
            with self.subTest(path=path), self.assertLogs(self.web.__name__, level="WARNING"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private upstream detail", response.text)
                self.assertNotIn("Notion에 저장된 공지가 없습니다.", response.text)
                self.assertIn("Notion 공지를 불러오지 못했습니다.", response.text)

    def test_missing_configuration_is_reported_as_failure(self):
        self.env.return_value = " "
        with self.assertLogs(self.web.__name__, level="WARNING"):
            response = self.client.get("/advisories")
        self.assertEqual(response.status_code, 503)
        self.notion.assert_not_called()

    def test_saved_text_is_escaped_and_missing_fields_render(self):
        self.rows.return_value = [notice(package_name='<script>alert("test")</script>'), {}]
        response = self.client.get("/advisories")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert("test")</script>', response.text)
        self.assertIn("&lt;script&gt;", response.text)
        self.assertIn("게시일 미확인 1건", response.text)


if __name__ == "__main__":
    unittest.main()
