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


SEVERITY_EMOJI = {
    "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡",
    "MODERATE": "🟡", "LOW": "🟢", "UNKNOWN": "⚪",
}

SOURCE_LABEL = {
    "kisa_security_notice": "KISA 보호나라 · 보안공지",
    "kisa_vulnerability": "KISA 보호나라 · 취약점 정보",
    "nvd": "NVD", "github_advisory": "GitHub Advisory",
}

def _send_blocks_payload(text_fallback: str, blocks: list) -> bool:
    """예쁘게 꾸며진 Block Kit 알림을 보내기 위한 전용 전송 함수"""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.error("슬랙 전송 실패: SLACK_WEBHOOK_URL이 없습니다.")
        return False
        
    try:
        response = requests.post(
            webhook_url,
            json={"text": text_fallback, "blocks": blocks},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200 or response.text.strip() != "ok":
            logger.error("슬랙 UI 블록 전송 실패 (HTTP %s)", response.status_code)
            return False
        return True
    except requests.RequestException as e:
        logger.error("슬랙 UI 블록 전송 실패: %s", type(e).__name__)
        return False

def send_cron_job_summary(raw_advisories: list) -> bool:
    """[요구사항 1] 영향도 High 목록 산출 완료 시 전송"""
    if not raw_advisories:
        return True
        
    total_count = len(raw_advisories)
    high_advisories = [
        item for item in raw_advisories 
        if (item.get("severity") or "").lower() in ["high", "critical"]
    ]
    high_count = len(high_advisories)
    
    if high_count == 0:
        list_text = "• High/Critical 위험 항목 없음"
    else:
        lines = []
        for item in high_advisories[:10]:
            emoji = SEVERITY_EMOJI.get((item.get("severity") or "UNKNOWN").upper(), "⚪")
            source = item.get("source", "unknown")
            label = SOURCE_LABEL.get(source, source)
            vuln_id = item.get("cve_id") or item.get("id", "N/A")
            title = item.get("title", "제목 없음")
            url = item.get("url", "")
            
            title_link = f"<{url}|{title}>" if url else title
            lines.append(f"{emoji} *[{label}]* `{vuln_id}` - {title_link}")
            
        if high_count > 10:
            lines.append(f"\n_... 외 {high_count - 10}건의 High/Critical 항목이 더 존재합니다._")
        list_text = "\n\n".join(lines)
        
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🚨 [보안 점검] 영향도 High 목록 산출 완료", "emoji": True}},
        {"type": "section", "fields": [{"type": "mrkdwn", "text": f"*총 수집 취약점:* {total_count} 건"}, {"type": "mrkdwn", "text": f"*High/Critical 취약점:* *{high_count} 건*"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*주요 High 취약점 목록:*\n{list_text[:2900]}"}},
        {"type": "divider"}
    ]
    
    return _send_blocks_payload(f"🚨 신규 High/Critical 취약점 {high_count}건 발견", blocks)

def send_mock_status_changed(asset_name: str, vuln_id: str, old_status: str = "Active", new_status: str = "inActive") -> bool:
    """[요구사항 2] Mock 데이터 상태 변경 완료 시 전송"""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🔄 *[Mock 데이터 상태 변경 완료]*\n취약점 영향도 평가에 따라 자산 운영 상태가 변경되었습니다.\n\n• *대상 자산:* {asset_name}\n• *원인 취약점:* `{vuln_id}`\n• *상태 변경:* `{old_status}` ➔ *`{new_status}`*"}},
        {"type": "divider"}
    ]
    return _send_blocks_payload(f"🔄 자산 상태 변경: {asset_name}", blocks)