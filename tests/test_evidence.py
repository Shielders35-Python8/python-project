"""취약 근거 화면 테스트"""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from source.web.evidence import build_evidence, exit_hint, filter_evidence, summarize

EXAMPLE = Path(__file__).resolve().parents[1] / "source" / "example"


def advisory(id_, name, version_range, severity="high", ecosystem="npm", **extra):
    return {"id": id_, "package_name": name, "ecosystem": ecosystem,
            "package_version_range": version_range, "severity": severity,
            "url": f"https://github.com/advisories/{id_}", **extra}


def package(id_, name, version, stored="safe", ecosystem="npm", services=("svc-1",)):
    return {"page_id": f"page-{id_}", "id": id_, "package_name": name, "ecosystem": ecosystem,
            "package_version": version, "vulnerability": stored, "service_id": list(services)}


SERVICES = [{"page_id": "svc-1", "id": "SVC-001", "resource_name": "order-service"},
            {"page_id": "svc-2", "id": "SVC-002", "resource_name": "auth-service"}]


class EvidenceRuleTests(unittest.TestCase):
    def test_highest_matched_severity_wins_and_range_boundaries_hold(self):
        rows = build_evidence(SERVICES, [package("PKG-1", "lib", "1.5.0")], [
            advisory("A", "lib", ">= 1.0.0, < 2.0.0", "medium"),
            advisory("B", "lib", "< 1.5.0", "critical"),        # 1.5.0 은 범위 밖
            advisory("C", "lib", "<= 1.5.0", "high"),           # 1.5.0 은 범위 안
            advisory("D", "other", "< 9.0", "critical"),        # 이름이 다름
            advisory("E", "lib", "< 9.0", "critical", ecosystem="pip"),  # 생태계가 다름
        ])
        row = rows[0]
        self.assertEqual(row["computed"], "high")
        self.assertEqual([a["id"] for a in row["matched"]], ["C", "A"])  # 심각도 높은 순
        self.assertEqual(row["candidate_count"], 3)

    def test_unknown_only_when_nothing_matched(self):
        beta = advisory("B", "lib", ">= 2.0.0-beta.1, < 2.0.0-beta.4", "critical")
        matched = build_evidence(SERVICES, [package("P", "lib", "1.0.0")],
                                 [beta, advisory("A", "lib", "< 1.1", "low")])[0]
        self.assertEqual((matched["computed"], len(matched["unknown"])), ("low", 1))
        only = build_evidence(SERVICES, [package("P", "lib", "1.0.0")], [beta])[0]
        self.assertEqual(only["computed"], "unknown")
        self.assertEqual(only["unknown"][0]["reason"], "공지 범위 표기")
        weird = build_evidence(SERVICES, [package("P", "lib", "v1.0")], [advisory("A", "lib", "< 2.0")])[0]
        self.assertEqual(weird["unknown"][0]["reason"], "설치 버전 표기")

    def test_github_unknown_severity_does_not_look_safe(self):
        row = build_evidence(SERVICES, [package("P", "lib", "1.0")],
                             [advisory("A", "lib", "< 2.0", "unknown")])[0]
        self.assertEqual(row["computed"], "unknown")
        self.assertEqual(row["matched"][0]["severity"], "미확인")

    def test_mismatch_and_whether_reanalysis_fixes_it(self):
        rows = {r["package_id"]: r for r in build_evidence(SERVICES, [
            package("OK", "a", "1.0", stored="high"),
            package("NEEDS-RUN", "a", "1.0", stored="safe"),
            package("STALE", "b", "5.0", stored="critical"),
            package("EMPTY", "c", "1.0", stored=None),
        ], [advisory("A", "a", "< 2.0", "high"), advisory("B", "b", "< 2.0", "critical")])}
        self.assertFalse(rows["OK"]["mismatch"])
        self.assertTrue(rows["NEEDS-RUN"]["mismatch"] and rows["NEEDS-RUN"]["mismatch_fixable"])
        self.assertTrue(rows["STALE"]["mismatch"])
        self.assertFalse(rows["STALE"]["mismatch_fixable"])   # 분석은 safe 로 되돌리지 않음
        self.assertFalse(rows["EMPTY"]["mismatch"])            # 미설정 + 근거 없음 = 불일치 아님

    def test_duplicate_notion_rows_are_shown_once(self):
        dup = advisory("A", "lib", "< 2.0")
        row = build_evidence(SERVICES, [package("P", "lib", "1.0")], [dup, dict(dup)])[0]
        self.assertEqual(len(row["matched"]), 1)

    def test_only_http_links_are_rendered(self):
        rows = build_evidence(SERVICES, [package("P", "lib", "1.0")], [
            advisory("X", "lib", "< 2.0", url="javascript:alert(1)"),
            advisory("Y", "lib", "< 3.0", url=" HTTPS://github.com/advisories/Y"),
        ])
        urls = {a["id"]: a["url"] for a in rows[0]["matched"]}
        self.assertIsNone(urls["X"])
        self.assertEqual(urls["Y"], "HTTPS://github.com/advisories/Y")

    def test_exit_hint_uses_single_upper_bound_only(self):
        for expression, expected in (
            (">= 1.0, < 1.7.4", "1.7.4 이상"), ("<= 19.2.25", "19.2.25 초과"),
            ("= 2.4.5", "2.4.5 외 버전"), (">= 1.0", None), (None, None),
            (">= 2.0.0-beta.1, < 2.0.0-beta.4", None),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(exit_hint(expression), expected)

    def test_filters_and_service_summary(self):
        rows = build_evidence(SERVICES, [
            package("P1", "a", "1.0", services=("svc-1",)),
            package("P2", "b", "1.0", services=("svc-2",)),
            package("P3", "c", "1.0", services=("svc-2",)),
        ], [advisory("A", "a", "< 2.0", "high", cve_id="CVE-2026-0001"),
            advisory("B", "b", "< 2.0", "critical")])
        self.assertEqual(len(filter_evidence(rows, "affected")), 2)
        self.assertEqual([r["package_id"] for r in filter_evidence(rows, "all", "cve-2026-0001")], ["P1"])
        self.assertEqual([r["package_id"] for r in filter_evidence(rows, "affected", service="SVC-002")], ["P2"])
        summary = summarize(rows)
        self.assertEqual([s["id"] for s in summary["services"]], ["SVC-002", "SVC-001"])  # critical 가진 쪽 먼저
        self.assertEqual(summary["affected"], 2)


class ProcessorConsistencyTests(unittest.TestCase):
    """processor.py 저장값과 판정 일치 여부 (mock 데이터)"""

    def test_same_result_as_processor_on_example_data(self):
        from source.services import processor

        advisories = json.loads((EXAMPLE / "advisories_mock.json").read_text(encoding="utf-8"))
        packages = json.loads((EXAMPLE / "service_package_mock.json").read_text(encoding="utf-8"))
        services = json.loads((EXAMPLE / "service_mock.json").read_text(encoding="utf-8"))

        class FakeNotion:
            saved = {}
            def get_database_rows(self, data_source_id, **_):
                return advisories if data_source_id == "adv" else packages
            def update_database_rows(self, page_id, properties):
                self.saved[page_id] = properties["vulnerability"]["select"]["name"]

        notion = FakeNotion()
        with patch.object(processor, "get_env", {"NOTION_ADVISORIES_DATA_SOURCE_ID": "adv",
                                                 "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID": "pkg"}.__getitem__), \
             patch.object(processor, "send_task_message"):
            processor._evaluate_impact(notion, None, None, lambda **_: None)

        rows = {row["page_id"]: row for row in build_evidence(services, packages, advisories)}
        for page_id, saved in notion.saved.items():
            with self.subTest(page_id=page_id):
                self.assertEqual(rows[page_id]["computed"], saved)
        # processor 가 저장하지 않은 패키지는 근거 화면에서도 safe 여야 한다.
        for page_id, row in rows.items():
            if page_id not in notion.saved:
                self.assertEqual(row["computed"], "safe", page_id)


class ScaleTests(unittest.TestCase):
    def test_large_data_is_fast(self):
        advisories = [advisory(f"A{i}", f"lib{i % 800}", f">= {i % 5}.0, < {i % 5 + 1}.0",
                               ("low", "medium", "high", "critical")[i % 4]) for i in range(6000)]
        packages = [package(f"P{i}", f"lib{i}", f"{i % 7}.5") for i in range(1000)]
        started = time.perf_counter()
        rows = build_evidence(SERVICES, packages, advisories)
        summarize(rows)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(len(rows), 1000)


class EvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("source.common.slack.notifications.send_error_message", return_value=False))
        from source.web.app import create_app
        self.data = {
            "NOTION_SERVICE_DATA_SOURCE_ID": SERVICES,
            "NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID": [package("PKG-1", "lib", "1.0"), package("PKG-2", "x", "v1")],
            "NOTION_ADVISORIES_DATA_SOURCE_ID": [
                advisory("GHSA-1", "lib", "< 2.0", "critical", title="<script>alert(1)</script>"),
                advisory("GHSA-2", "x", "< 2.0"),
            ],
        }
        self.app = create_app()
        self.app.extensions["dashboard_cache"].loader = self.data.__getitem__
        self.client = self.app.test_client()

    def ready(self, url="/evidence"):
        self.client.get(url)
        for _ in range(50):
            if self.app.extensions["dashboard_cache"].status(tuple(self.data))["ready"]:
                break
            time.sleep(0.02)
        return self.client.get(url)

    def test_loading_page_then_evidence(self):
        first = self.client.get("/evidence")
        self.assertEqual(first.status_code, 200)
        page = self.ready().get_data(as_text=True)
        self.assertIn("GHSA-1", page)
        self.assertNotIn("<script>alert(1)</script>", page)   # 공지 제목은 이스케이프된다
        self.assertIn("&lt;script&gt;", page)

    def test_bad_params_do_not_break_page(self):
        for url in ("/evidence?view=zzz", "/evidence?page=-3", "/evidence?page=abc",
                    "/evidence?service=NOPE", "/evidence?q=" + "a" * 500, "/evidence?view=unknown&page=99"):
            with self.subTest(url=url):
                self.assertEqual(self.ready(url).status_code, 200)

    def test_page_never_writes_to_notion(self):
        with patch("source.common.notion.notion.NotionClient.update_database_rows") as update, \
             patch("source.common.notion.notion.NotionClient.create_database_row") as create:
            self.ready("/evidence?view=all")
        update.assert_not_called()
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
