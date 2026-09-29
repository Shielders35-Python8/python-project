"""프로젝트 실행과 결과 조회를 위한 Flask 웹 대시보드.

프로젝트 루트에서 실행: python -m source.web.app
개발 모드: python -m flask --app source.web.app run --debug
"""

from flask import Flask, jsonify, render_template


def create_app() -> Flask:
    """웹 앱을 생성한다. 서버 시작 시 수집이나 스케줄러를 실행하지 않는다."""
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/")
    def dashboard():
        # TODO: 저장소 조회 함수를 연결하고 실제 결과를 템플릿에 전달한다.
        return render_template("index.html", results=[])

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
        # 장시간 작업이나 무한 루프 스케줄러는 요청 안에서 직접 실행하지 않는다.
        return jsonify(
            status="not_implemented",
            message="프로젝트 실행 기능이 아직 연결되지 않았습니다.",
        ), 501

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
