"""프로젝트 실행과 결과 조회를 위한 Flask 웹 대시보드.

프로젝트 루트에서 실행: python -m source.web.app
개발 모드: python -m flask --app source.web.app run --debug
"""

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template

# README에 안내한 파일 직접 실행 방식도 패키지 import가 가능하게 한다.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from source.common.slack.notifications import init_app


def create_app() -> Flask:
    """웹 앱을 생성한다. 서버 시작 시 공지 수집을 실행하지 않는다."""
    app = Flask(__name__)
    app.json.ensure_ascii = False
    init_app(app)

    def render_dashboard_page(active_page: str):
        page_content = {
            "dashboard": (
                "보안 공지 대시보드",
                "보안 공지와 서비스별 패키지를 살펴보고, 취약점의 영향을 확인합니다.",
            ),
            "run_status": (
                "실행 상태",
                "보안 공지 수집부터 분석, 저장까지 실행 상태와 기록을 확인합니다.",
            ),
            "results": (
                "분석 결과",
                "서비스별 설치 버전과 보안 공지의 취약 범위를 비교합니다.",
            ),
        }
        title, description = page_content[active_page]
        # TODO: 저장소 조회 함수를 연결하고 실제 결과를 템플릿에 전달한다.
        return render_template(
            "index.html",
            results=[],
            active_page=active_page,
            page_title=title,
            page_description=description,
        )

    @app.get("/")
    def dashboard():
        return render_dashboard_page("dashboard")

    @app.get("/run-status")
    def run_status():
        return render_dashboard_page("run_status")

    @app.get("/results")
    def analysis_results():
        return render_dashboard_page("results")

    @app.get("/api/health")
    def health():
        """웹 서버의 응답 여부만 확인한다. 외부 서비스 상태는 포함하지 않는다."""
        return jsonify(status="ok", service="project-dashboard")

    @app.get("/api/results")
    def get_results():
        # TODO: 저장된 분석 결과를 조회한다.
        return jsonify(
            status="not_connected",
            message="결과 저장소가 아직 연결되지 않았습니다.",
            results=[],
        )

    @app.post("/api/run")
    def run_project():
        # TODO: 수집 → 분석 → 저장 작업을 연결한다.
        # 장시간 작업은 요청 안에서 직접 실행하지 않는다.
        return jsonify(
            status="not_implemented",
            message="프로젝트 실행 기능이 아직 연결되지 않았습니다.",
        ), 501

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
