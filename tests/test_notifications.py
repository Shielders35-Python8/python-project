import importlib
import io
import logging
import subprocess
import sys
import threading
import unittest
from itertools import permutations
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from flask import Flask, abort

from source.common.github_advisory import advisories
from source.common.notion.notion import NotionClient
from source.common.slack import notifications
from source.config import config
from source.services import processor


SAVE_RESPONSE = advisories.make_response_json
ADVISORY = {
    "ghsa_id": "GHSA-test", "summary": "Test advisory", "severity": "high",
    "cvss_severities": {"cvss_v3": {"score": 8.0}}, "vulnerabilities": [],
}


class NotificationTestCase(unittest.TestCase):
    def setUp(self):
        # 어떤 테스트 경로에서도 Slack/GitHub/Notion에 실제 요청하지 않는다.
        self.enterContext(patch.object(
            requests.sessions.Session, "request",
            side_effect=AssertionError("External network is disabled in tests"),
        ))
        self.send = self.enterContext(patch(
            "source.common.slack.slack._send_message", return_value=True,
        ))
        root = logging.getLogger()
        handlers = root.handlers[:]
        self.addCleanup(setattr, root, "handlers", handlers)
        self.logs = io.StringIO()
        root.handlers = [logging.StreamHandler(self.logs)]
        self.enterContext(patch.object(sys, "excepthook", Mock()))
        self.enterContext(patch.object(threading, "excepthook", Mock()))
        self.enterContext(patch.object(notifications, "_previous_excepthook", Mock()))
        self.enterContext(patch.object(notifications, "_previous_thread_excepthook", Mock()))

    def messages(self):
        return [call.args[0] for call in self.send.call_args_list]


class GithubNotificationTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.save = self.enterContext(patch.object(advisories, "make_response_json"))
        self.enterContext(patch.object(advisories, "print", create=True))
        self.enterContext(patch.object(advisories.time, "sleep"))
        self.get = self.enterContext(patch.object(advisories.requests, "get"))
        self.response = Mock(status_code=200)
        self.response.json.return_value = [ADVISORY]
        self.get.return_value = self.response

    def test_success_notifies_with_actual_count(self):
        result = advisories.get_advisories()
        self.assertEqual(result[0]["id"], "GHSA-test")
        self.save.assert_called_once_with(result)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("수집 1건", self.messages()[0])

    def test_empty_success_still_notifies(self):
        self.response.json.return_value = []
        self.assertEqual(advisories.get_advisories(), [])
        self.assertIn("수집 0건", self.messages()[0])

    def test_each_failed_attempt_notifies_without_success(self):
        self.get.side_effect = [requests.Timeout(f"timeout {n}") for n in range(3)]
        self.assertEqual(advisories.get_advisories(), [])
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual(len(self.messages()), 3)
        self.assertTrue(all(message.startswith("[오류]") for message in self.messages()))
        self.assertIn("시도 3/3", self.messages()[-1])
        self.save.assert_not_called()

    def test_retry_recovery_sends_error_then_success(self):
        self.get.side_effect = [requests.Timeout("timeout"), self.response]
        self.assertEqual(len(advisories.get_advisories()), 1)
        self.assertTrue(self.messages()[0].startswith("[오류]"))
        self.assertTrue(self.messages()[1].startswith("[작업]"))

    def test_http_errors_notify_and_preserve_retry_policy(self):
        for status, attempts in ((401, 1), (503, 3)):
            with self.subTest(status=status):
                self.send.reset_mock()
                self.get.reset_mock()
                self.response.raise_for_status.side_effect = [
                    requests.HTTPError("upstream failure", response=Mock(status_code=status))
                    for _ in range(attempts)
                ]
                self.assertEqual(advisories.get_advisories(), [])
                self.assertEqual(self.get.call_count, attempts)
                self.assertEqual(len(self.messages()), attempts)
                self.assertTrue(all(m.startswith("[오류]") for m in self.messages()))

    def test_parse_failure_does_not_notify_completion(self):
        self.response.json.side_effect = ValueError("invalid JSON")
        self.assertEqual(advisories.get_advisories(), [])
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("ValueError: invalid JSON", self.messages()[0])
        self.save.assert_not_called()

    def test_file_save_failure_notifies_but_collection_still_succeeded(self):
        self.save.side_effect = SAVE_RESPONSE
        with patch("builtins.open", side_effect=OSError("disk full")):
            self.assertEqual(len(advisories.get_advisories()), 1)
        self.assertIn("파일 저장", self.messages()[0])
        self.assertIn("수집 1건", self.messages()[1])


class AnalysisNotificationTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.factory = self.enterContext(patch.object(processor, "NotionClient"))
        self.notion = self.factory.return_value
        self.enterContext(patch.object(processor, "get_env", side_effect=lambda key: key))
        self.advisory = {
            "package_name": "demo", "ecosystem": "pip",
            "package_version_range": "<2.0", "severity": "high",
        }
        self.package = {
            "page_id": "page-1", "package_name": "demo",
            "ecosystem": "pip", "package_version": "1.0",
        }
        self.notion.get_database_rows.side_effect = [[self.advisory], [self.package]]

    def test_completion_follows_all_notion_updates(self):
        events = []
        self.notion.update_database_rows.side_effect = lambda **kwargs: events.append("save")
        self.send.side_effect = lambda message: events.append("notify") or True
        self.assertEqual(processor.evaluate_impact("2026-09-01", "2026-09-30")["updated_count"], 1)
        self.assertEqual(events, ["save", "notify"])
        self.assertIn("영향 패키지 1개", self.messages()[0])
        self.assertIn("2026-09-01 ~ 2026-09-30", self.messages()[0])

    def test_no_matches_is_a_successful_analysis(self):
        self.package["package_version"] = "3.0"
        processor.evaluate_impact("2026-09-01", "2026-09-30")
        self.notion.update_database_rows.assert_not_called()
        self.assertIn("취약점 일치 0건", self.messages()[0])

    def test_highest_severity_is_saved_once_regardless_of_advisory_order(self):
        severities = ("low", "medium", "high", "critical")
        for size in range(1, len(severities) + 1):
            for order in permutations(severities[:size]):
                with self.subTest(order=order):
                    self.notion.update_database_rows.reset_mock()
                    self.send.reset_mock()
                    self.notion.get_database_rows.side_effect = [
                        [dict(self.advisory, severity=value) for value in order],
                        [self.package],
                    ]
                    processor.evaluate_impact("2026-09-01", "2026-09-30")
                    self.notion.update_database_rows.assert_called_once_with(
                        page_id="page-1",
                        properties={"vulnerability": {"select": {"name": severities[size - 1]}}},
                    )
                    self.assertIn(f"취약점 일치 {size}건 / 영향 패키지 1개", self.messages()[0])

    def test_uncomparable_version_or_range_is_saved_as_unknown(self):
        for version, expression in (("1.0", "< 2.0-rc..1"), ("1.0-beta..1", "< 2.0"),
                                    (None, "< 2.0"), ("1.0", None)):
            with self.subTest(version=version, expression=expression):
                self.notion.update_database_rows.reset_mock()
                self.send.reset_mock()
                self.notion.get_database_rows.side_effect = [
                    [dict(self.advisory, package_version_range=expression)],
                    [dict(self.package, package_version=version)],
                ]
                processor.evaluate_impact(None, None)
                self.notion.update_database_rows.assert_called_once_with(
                    page_id="page-1", properties={"vulnerability": {"select": {"name": "unknown"}}},
                )
                self.assertIn("영향 패키지 0개 / 알 수 없음 1개", self.messages()[0])

    def test_unknown_does_not_hide_confirmed_highest_severity(self):
        advisories = [dict(self.advisory, package_version_range="< 2.0-rc..1"),
                      dict(self.advisory, severity="critical"), self.advisory]
        for order in permutations(advisories):
            self.notion.update_database_rows.reset_mock()
            self.send.reset_mock()
            self.notion.get_database_rows.side_effect = [list(order), [self.package]]
            processor.evaluate_impact(None, None)
            self.notion.update_database_rows.assert_called_once_with(
                page_id="page-1", properties={"vulnerability": {"select": {"name": "critical"}}},
            )
            self.assertIn("영향 패키지 1개 / 알 수 없음 0개", self.messages()[0])

    def test_multiple_unknown_ranges_save_once_even_with_a_numeric_nonmatch(self):
        self.notion.get_database_rows.side_effect = [
            [dict(self.advisory, package_version_range=value)
             for value in ("< 2.0-rc..1", ">= 4.0-beta..1", "< 2.0")],
            [dict(self.package, package_version="3.0")],
        ]
        processor.evaluate_impact(None, None)
        self.notion.update_database_rows.assert_called_once_with(
            page_id="page-1", properties={"vulnerability": {"select": {"name": "unknown"}}},
        )

    def test_unrelated_unsupported_ranges_do_not_mark_package_unknown(self):
        self.notion.get_database_rows.side_effect = [
            [dict(self.advisory, package_name="other", package_version_range="< 2.0-rc..1"),
             dict(self.advisory, ecosystem="npm", package_version_range="< 2.0-rc..1")],
            [self.package],
        ]
        processor.evaluate_impact(None, None)
        self.notion.update_database_rows.assert_not_called()

    def test_resolved_unknown_is_not_cleared_by_a_partial_period_analysis(self):
        self.package.update(package_version="3.0", vulnerability="unknown")
        processor.evaluate_impact("2026-09-01", "2026-09-30")
        self.notion.update_database_rows.assert_not_called()

    def test_unknown_is_retained_when_any_related_range_is_still_unsupported(self):
        self.notion.get_database_rows.side_effect = [
            [self.advisory, dict(self.advisory, package_version_range="< latest")],
            [dict(self.package, package_version="3.0", vulnerability="unknown")],
        ]
        processor.evaluate_impact(None, None)
        self.notion.update_database_rows.assert_called_once_with(
            page_id="page-1", properties={"vulnerability": {"select": {"name": "unknown"}}},
        )

    def test_each_package_gets_its_own_highest_matching_severity(self):
        self.notion.get_database_rows.side_effect = [
            [dict(self.advisory, severity="critical"),
             dict(self.advisory, severity="high", package_version_range="<3.0"),
             dict(self.advisory, severity="low", package_version_range="<3.0")],
            [self.package, dict(self.package, page_id="page-2", package_version="2.5")],
        ]
        processor.evaluate_impact("2026-09-01", "2026-09-30")
        calls = self.notion.update_database_rows.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            {call.kwargs["page_id"]: call.kwargs["properties"]["vulnerability"]["select"]["name"]
             for call in calls},
            {"page-1": "critical", "page-2": "high"},
        )
        self.assertIn("취약점 일치 5건 / 영향 패키지 2개", self.messages()[0])

    def test_duplicate_matches_and_severity_case_do_not_change_maximum(self):
        self.notion.get_database_rows.side_effect = [
            [dict(self.advisory, severity=value) for value in (" HIGH ", "high", "medium")],
            [self.package],
        ]
        processor.evaluate_impact("2026-09-01", "2026-09-30")
        self.notion.update_database_rows.assert_called_once_with(
            page_id="page-1", properties={"vulnerability": {"select": {"name": "high"}}},
        )

    def test_invalid_matching_severity_stops_before_any_write(self):
        for severity in (None, "", "unknown", "safe"):
            with self.subTest(severity=severity):
                self.send.reset_mock()
                self.notion.get_database_rows.side_effect = [
                    [self.advisory, dict(self.advisory, severity=severity)], [self.package],
                ]
                with self.assertRaises(ValueError):
                    processor.evaluate_impact("2026-09-01", "2026-09-30")
                self.notion.update_database_rows.assert_not_called()
                self.assertEqual(len(self.messages()), 1)
                self.assertTrue(self.messages()[0].startswith("[오류]"))

    def test_partial_update_failure_never_notifies_completion(self):
        other = dict(self.package, page_id="page-2")
        self.notion.get_database_rows.side_effect = [[self.advisory], [self.package, other]]
        error = RuntimeError("Notion unavailable")
        self.notion.update_database_rows.side_effect = [None, error]
        with self.assertRaises(RuntimeError) as caught:
            processor.evaluate_impact("start", "end")
        self.assertIs(caught.exception, error)
        self.assertEqual(self.notion.update_database_rows.call_count, 2)
        self.assertEqual(len(self.messages()), 1)
        self.assertTrue(self.messages()[0].startswith("[오류]"))

    def test_query_failure_notifies_without_completion(self):
        self.notion.get_database_rows.side_effect = RuntimeError("query failed")
        with self.assertRaises(RuntimeError):
            processor.evaluate_impact("start", "end")
        self.assertEqual(len(self.messages()), 1)
        self.assertTrue(self.messages()[0].startswith("[오류]"))

    def test_notion_error_crossing_analysis_boundary_is_reported_once(self):
        client = object.__new__(NotionClient)
        client.client = Mock()
        client.client.pages.update.side_effect = RuntimeError("write failed")
        self.notion.update_database_rows.side_effect = client.update_database_rows
        with self.assertRaises(RuntimeError):
            processor.evaluate_impact("start", "end")
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("Notion 결과 저장", self.messages()[0])


class ServerNotificationTests(NotificationTestCase):
    def make_app(self):
        app = Flask(__name__)
        app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
        notifications.init_app(app)
        return app

    def test_unhandled_request_error_sends_once_and_preserves_500(self):
        app = self.make_app()

        @app.get("/broken")
        @notifications.notify_errors("작업")
        def broken():
            raise RuntimeError("broken operation")

        response = app.test_client().get("/broken?token=do-not-send")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("broken operation", self.messages()[0])
        self.assertNotIn("do-not-send", self.messages()[0])

    def test_unhandled_request_error_without_decorator_sends_once(self):
        app = self.make_app()

        @app.get("/broken")
        def broken():
            raise RuntimeError("unexpected")

        self.assertEqual(app.test_client().get("/broken").status_code, 500)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("GET /broken", self.messages()[0])

    def test_debug_mode_still_reports_and_preserves_exception(self):
        app = self.make_app()
        app.config.update(DEBUG=True, PROPAGATE_EXCEPTIONS=True)

        @app.get("/broken")
        def broken():
            raise RuntimeError("debug exception")

        with self.assertRaises(RuntimeError):
            app.test_client().get("/broken")
        self.assertEqual(len(self.messages()), 1)

    def test_5xx_responses_and_abort_are_reported_but_4xx_are_not(self):
        app = self.make_app()

        @app.get("/status/<int:status>")
        def status_response(status):
            return {"status": "test"}, status

        @app.get("/abort")
        def abort_response():
            abort(503)

        client = app.test_client()
        for code in (500, 501, 502, 503, 504):
            response = client.get(f"/status/{code}")
            self.assertEqual(response.status_code, code)
            self.assertIn(f"HTTP {code}", self.messages()[-1])
        self.assertEqual(client.get("/abort").status_code, 503)
        self.assertEqual(len(self.messages()), 6)
        client.get("/missing")
        client.post("/abort")
        client.get("/status/400")
        self.assertEqual(len(self.messages()), 6)

    def test_registration_is_idempotent_and_logs_are_forwarded(self):
        app = self.make_app()
        notifications.init_app(app)
        notifications.install_error_notifications()
        logging.getLogger("project.worker").error("background error %s", 42)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("background error 42", self.messages()[0])
        logging.getLogger("project.worker").warning("not an error")
        logging.getLogger("source.common.slack.slack").error("webhook unavailable")
        self.assertEqual(len(self.messages()), 1)

    def test_notification_failure_does_not_recurse_or_replace_error(self):
        app = self.make_app()
        self.send.side_effect = RuntimeError("sender failed")

        @app.get("/broken")
        def broken():
            raise ValueError("original error")

        response = app.test_client().get("/broken")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.send.call_count, 1)
        self.assertIn("ValueError: original error", self.messages()[0])

    def test_process_and_thread_hooks_keep_original_handlers(self):
        process_hook, thread_hook = sys.excepthook, threading.excepthook
        notifications.install_error_notifications()
        error = RuntimeError("process failed")
        sys.excepthook(type(error), error, None)
        process_hook.assert_called_once_with(type(error), error, None)
        args = SimpleNamespace(
            exc_type=ValueError, exc_value=ValueError("thread failed"),
            exc_traceback=None, thread=SimpleNamespace(name="worker"),
        )
        threading.excepthook(args)
        thread_hook.assert_called_once_with(args)
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("worker", self.messages()[1])
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(len(self.messages()), 2)

    def test_settings_load_failure_reports_after_retry(self):
        with patch("builtins.open", side_effect=OSError("configuration missing")), \
                patch.object(config.time, "sleep"):
            with self.assertRaises(OSError):
                config.load_config()
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("서버 설정 로딩", self.messages()[0])

    def test_real_dashboard_app_has_notifications(self):
        app_module = importlib.import_module("source.web.app")
        app = app_module.create_app()
        @app.get("/test-server-error")
        def server_error():
            return "error", 503
        client = app.test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.send.assert_not_called()
        self.assertEqual(client.get("/test-server-error").status_code, 503)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("GET /test-server-error: HTTP 503", self.messages()[0])

    def test_dashboard_direct_file_import_works_without_project_on_sys_path(self):
        # -I는 현재 디렉터리를 sys.path에서 제외한다. 실제 서버는 띄우지 않는다.
        result = subprocess.run(
            [sys.executable, "-B", "-I", "-c",
             "import runpy; from unittest.mock import patch; "
             "from flask import Flask; "
             "guard = patch('requests.sessions.Session.request', "
             "side_effect=AssertionError('network disabled')); guard.start(); "
             "server = patch.object(Flask, 'run'); server.start(); "
             "runpy.run_path('source/web/app.py', run_name='__main__')"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_entry_point_reports_unexpected_errors(self):
        main = importlib.import_module("main")
        with patch.object(main, "get_advisories", side_effect=RuntimeError("CLI failure")), \
                patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                main.main()
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("CLI failure", self.messages()[0])

    def test_install_preserves_console_logging_when_no_handlers_exist(self):
        logging.getLogger().handlers = []
        with patch.object(sys, "stderr", self.logs):
            notifications.install_error_notifications()
            logging.error("keep this local error")
        self.assertIn("keep this local error", self.logs.getvalue())
        self.assertEqual(len(self.messages()), 1)


if __name__ == "__main__":
    unittest.main()
