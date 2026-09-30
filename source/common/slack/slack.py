"""SLACK_WEBHOOK_URL에 연결된 채널로 오류 및 작업 알림을 전송한다."""

import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# 설정 파일 로딩 자체가 실패해도 오류 알림을 보낼 수 있게 독립적으로 읽는다.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")
logger = logging.getLogger(__name__)


def _send_message(text: str) -> bool:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    if not webhook_url:
        logger.error("슬랙 전송 실패: SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return False

    # 예외나 로그에 섞인 환경변수의 인증 정보를 채널에 노출하지 않는다.
    secrets = [
        value for key, value in os.environ.items()
        if value and (any(word in key.upper() for word in
                          ("TOKEN", "SECRET", "PASSWORD", "WEBHOOK"))
                      or key.upper().endswith("_KEY"))
    ]
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")

    # 오류 내용에 포함된 <...> 등이 슬랙 멘션으로 해석되지 않도록 한다.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        response = requests.post(
            webhook_url,
            json={"text": text, "mrkdwn": False},
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        # 예외 문자열에는 비밀 정보인 웹훅 URL이 포함될 수 있다.
        logger.error("슬랙 전송 실패: %s", type(error).__name__)
        return False

    if response.status_code != 200 or response.text.strip() != "ok":
        logger.error("슬랙 전송 실패: 응답을 확인하세요 (HTTP %s).", response.status_code)
        return False
    return True


def _format_message(category: str, message: str, task_name: str | None) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message는 비어 있지 않은 문자열이어야 합니다.")

    title = f"[{category}]"
    if task_name:
        title += f" {task_name}"
    return f"{title}\n{message}"


def send_error_message(
    message: str,
    error: Exception | None = None,
    *,
    task_name: str | None = None,
) -> bool:
    """오류 알림을 전송하며, error가 있으면 예외 종류와 내용을 함께 보낸다.

    SLACK_WEBHOOK_URL은 .env 또는 환경변수에서 읽는다.
    성공 시 True, 설정 누락 또는 전송 실패 시 로그를 남기고 False를 반환한다.
    비어 있거나 문자열이 아닌 message는 ValueError를 발생시킨다.
    """
    text = _format_message("오류", message, task_name)
    if error is not None:
        text += f"\n{type(error).__name__}: {error}"
    return _send_message(text)


def send_task_message(message: str, *, task_name: str | None = None) -> bool:
    """작업 시작, 진행 상황, 완료 등 작업 알림을 전송한다.

    SLACK_WEBHOOK_URL은 .env 또는 환경변수에서 읽는다.
    성공 시 True, 설정 누락 또는 전송 실패 시 로그를 남기고 False를 반환한다.
    비어 있거나 문자열이 아닌 message는 ValueError를 발생시킨다.
    """
    return _send_message(_format_message("작업", message, task_name))
