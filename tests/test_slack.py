import unittest
from unittest.mock import Mock, patch

import requests

from source.common.slack.slack import send_error_message, send_task_message


MODULE = "source.common.slack.slack"


class SlackMessageTests(unittest.TestCase):
    def setUp(self):
        self.post = self.enterContext(patch(f"{MODULE}.requests.post"))
        self.get_env = self.enterContext(patch(f"{MODULE}.get_env"))
        self.get_env.return_value = "https://hooks.slack.com/services/test-only"
        self.post.return_value = Mock(status_code=200, text="ok")

    def test_task_message_posts_json_with_timeout(self):
        self.assertTrue(send_task_message("분석 완료", task_name="취약점 분석"))
        self.get_env.assert_called_once_with("SLACK_WEBHOOK_URL")
        self.post.assert_called_once_with(
            self.get_env.return_value,
            json={"text": "[작업] 취약점 분석\n분석 완료", "mrkdwn": False},
            timeout=10,
            allow_redirects=False,
        )

    def test_error_message_includes_exception_and_task(self):
        self.assertTrue(
            send_error_message(
                "분석 실패", ValueError("잘못된 날짜"), task_name="취약점 분석"
            )
        )
        self.assertEqual(
            self.post.call_args.kwargs["json"]["text"],
            "[오류] 취약점 분석\n분석 실패\nValueError: 잘못된 날짜",
        )

    def test_optional_arguments_can_be_omitted(self):
        for send, category in ((send_task_message, "작업"), (send_error_message, "오류")):
            with self.subTest(category=category):
                self.assertTrue(send("알림"))
                self.assertEqual(
                    self.post.call_args.kwargs["json"]["text"], f"[{category}]\n알림"
                )

    def test_message_content_cannot_create_slack_mentions(self):
        self.assertTrue(send_error_message("<!channel> & <실패>"))
        self.assertEqual(
            self.post.call_args.kwargs["json"]["text"],
            "[오류]\n&lt;!channel&gt; &amp; &lt;실패&gt;",
        )

    def test_invalid_message_does_not_send(self):
        for send in (send_task_message, send_error_message):
            for message in ("", " \n", None, 123):
                with self.subTest(send=send.__name__, message=message):
                    with self.assertRaises(ValueError):
                        send(message)
        self.post.assert_not_called()

    def test_missing_webhook_returns_false_without_sending(self):
        self.get_env.side_effect = KeyError("SLACK_WEBHOOK_URL")
        with self.assertLogs(MODULE, level="ERROR"):
            self.assertFalse(send_error_message("분석 실패"))
        self.post.assert_not_called()

    def test_blank_webhook_returns_false_without_sending(self):
        self.get_env.return_value = "  "
        with self.assertLogs(MODULE, level="ERROR"):
            self.assertFalse(send_task_message("분석 시작"))
        self.post.assert_not_called()

    def test_network_failures_return_false_without_exposing_webhook(self):
        for exception in (
            requests.Timeout,
            requests.ConnectionError,
            requests.exceptions.InvalidURL,
        ):
            with self.subTest(exception=exception.__name__):
                self.post.side_effect = exception(self.get_env.return_value)
                with self.assertLogs(MODULE, level="ERROR") as logs:
                    self.assertFalse(send_error_message("분석 실패"))
                self.assertNotIn(self.get_env.return_value, "\n".join(logs.output))

    def test_unsuccessful_responses_return_false_without_retry(self):
        for status, text in (
            (400, "invalid_payload"),
            (429, "rate_limited"),
            (500, "server_error"),
            (302, ""),
            (200, "invalid_token"),
        ):
            with self.subTest(status=status, text=text):
                self.post.reset_mock()
                self.post.return_value = Mock(status_code=status, text=text)
                with self.assertLogs(MODULE, level="ERROR"):
                    self.assertFalse(send_task_message("분석 시작"))
                self.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
