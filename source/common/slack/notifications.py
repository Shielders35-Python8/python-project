"""작업 오류와 서버 예외를 기존 동작을 유지하면서 슬랙에 알린다."""

import logging
import sys
import threading
from functools import wraps

from source.common.slack.slack import send_error_message


_sending = threading.local()
_previous_excepthook = sys.excepthook
_previous_thread_excepthook = threading.excepthook


def report_error(message, error=None, *, task_name=None):
    """같은 예외가 여러 계층을 통과해도 한 번만 전송을 시도한다."""
    if getattr(_sending, "active", False):
        return False
    if error is not None:
        if getattr(error, "_slack_notification_attempted", False):
            return False
        error._slack_notification_attempted = True

    _sending.active = True
    try:
        return send_error_message(message, error, task_name=task_name)
    except Exception:
        # 알림 실패가 원래 예외나 서버 응답을 바꾸지 않도록 한다.
        logging.getLogger(__name__).error("슬랙 오류 알림 처리에 실패했습니다.")
        return False
    finally:
        _sending.active = False


def notify_errors(task_name):
    """호출자가 예외를 처리하더라도 작업 실패를 기록하고 원래 예외를 전달한다."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as error:
                report_error("작업 중 오류가 발생했습니다.", error, task_name=task_name)
                raise
        return wrapped
    return decorate


class SlackErrorHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        # 웹훅 전송 실패 로그를 다시 웹훅으로 보내는 순환을 막는다.
        if record.name.startswith("source.common.slack."):
            return
        try:
            error = record.exc_info[1] if record.exc_info else None
            report_error(record.getMessage(), error, task_name=record.name)
        except Exception:
            self.handleError(record)


def _handle_uncaught(exc_type, error, traceback):
    if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        report_error("처리되지 않은 실행 오류입니다.", error, task_name="서버 실행")
    _previous_excepthook(exc_type, error, traceback)


def _handle_thread_uncaught(args):
    if not issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        report_error(
            "백그라운드 스레드에서 처리되지 않은 오류입니다.",
            args.exc_value,
            task_name=args.thread.name if args.thread else "백그라운드 작업",
        )
    _previous_thread_excepthook(args)


def install_error_notifications():
    """프로세스당 한 번 ERROR 이상 로그와 메인/스레드 미처리 예외를 연결한다."""
    global _previous_excepthook, _previous_thread_excepthook
    root = logging.getLogger()
    if not root.handlers:
        # 슬랙 핸들러 추가로 logging의 기본 콘솔 출력이 사라지지 않게 한다.
        logging.basicConfig()
    if not any(isinstance(handler, SlackErrorHandler) for handler in root.handlers):
        root.addHandler(SlackErrorHandler())
    if sys.excepthook is not _handle_uncaught:
        _previous_excepthook = sys.excepthook
        sys.excepthook = _handle_uncaught
    if threading.excepthook is not _handle_thread_uncaught:
        _previous_thread_excepthook = threading.excepthook
        threading.excepthook = _handle_thread_uncaught


def init_app(app):
    """Flask 예외(디버그 모드 포함)와 명시적인 HTTP 5xx 응답을 알린다."""
    from flask import g, got_request_exception, request

    install_error_notifications()
    if "slack_notifications" in app.extensions:
        return

    def on_exception(sender, exception, **extra):
        g._slack_request_exception = True
        report_error(
            f"{request.method} {request.path} 요청 처리 중 오류가 발생했습니다.",
            exception,
            task_name="웹 서버",
        )

    def on_response(response):
        if response.status_code >= 500 and not getattr(g, "_slack_request_exception", False):
            report_error(
                f"{request.method} {request.path}: HTTP {response.status_code}",
                task_name="웹 서버",
            )
        return response

    got_request_exception.connect(on_exception, sender=app, weak=False)
    app.after_request(on_response)
    app.extensions["slack_notifications"] = on_exception
