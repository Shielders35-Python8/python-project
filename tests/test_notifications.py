import importlib
import io
import logging
import subprocess
import sys
import threading
import unittest
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
        self.assertIsNone(processor.evaluate_impact("2026-09-01", "2026-09-30"))
        self.assertEqual(events, ["save", "notify"])
        self.assertIn("영향 패키지 1개", self.messages()[0])
        self.assertIn("2026-09-01 ~ 2026-09-30", self.messages()[0])

    def test_no_matches_is_a_successful_analysis(self):
        self.package["package_version"] = "3.0"
        processor.evaluate_impact("2026-09-01", "2026-09-30")
        self.notion.update_database_rows.assert_not_called()
        self.assertIn("취약점 일치 0건", self.messages()[0])

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
        client = app.test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.send.assert_not_called()
        self.assertEqual(client.post("/api/run").status_code, 501)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("POST /api/run: HTTP 501", self.messages()[0])

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


class PreviewNotificationTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        save = advisories.make_response_json
        self.preview = importlib.import_module("source.web.preview_app")
        # 미리보기의 기존 파일 저장 비활성화가 다른 테스트에 영향을 주지 않게 복원한다.
        advisories.make_response_json = save
        self.enterContext(patch.dict(self.preview.STATE, clear=False))
        notifications.init_app(self.preview.app)

    def test_fetch_notifies_demo_analysis_once_without_refresh_notifications(self):
        with patch.object(advisories, "get_advisories", return_value=[{"id": "test"}]):
            client = self.preview.app.test_client()
            self.assertEqual(client.post("/fetch", follow_redirects=True).status_code, 200)
            self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("mock 서비스·패키지 기준", self.messages()[0])

    def test_failed_fetch_does_not_notify_analysis_completion(self):
        with patch.object(advisories, "get_advisories", return_value=[]):
            self.assertEqual(self.preview.app.test_client().post("/fetch").status_code, 302)
        self.send.assert_not_called()

    def test_preview_server_errors_are_connected(self):
        with patch.object(self.preview, "build_page_data", side_effect=RuntimeError("preview failed")):
            response = self.preview.app.test_client().get("/")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("preview failed", self.messages()[0])

    def test_missing_preview_input_does_not_notify_completion(self):
        with patch.object(advisories, "get_advisories", return_value=[{"id": "test"}]), \
                patch("builtins.open", side_effect=OSError("missing mock")), \
                patch("builtins.print"):
            response = self.preview.app.test_client().post("/fetch")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.messages()), 1)
        self.assertTrue(self.messages()[0].startswith("[오류]"))


if __name__ == "__main__":
    unittest.main()
