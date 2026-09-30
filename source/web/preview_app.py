"""
    [임시 미리보기 v2] 시각화 시안 확인용 Flask 앱 - 커밋하지 않는 로컬 전용 파일

    - 팀원 파일은 수정하지 않는다. (가져다 쓰기만 함)
    - 실행 (프로젝트 루트에서): python -m source.web.preview_app
    - 접속: http://127.0.0.1:5001

    화면 구성
      1) [최신 공지 가져오기] 버튼 → 시원님의 get_advisories() 로 GitHub 에 실제 요청
      2) 보안 공지 카드 목록 → 클릭하면 오른쪽 상세 패널
      3) 서비스(mock) 현황 + 영향 분석 결과 + 차트
"""
import json
import re
from collections import Counter
from datetime import datetime

from flask import Flask, redirect, render_template, url_for

import source.common.github_advisory.advisories as advisory_module

MOCK_DIR = "source/example"
SEVERITY_ORDER = ["critical", "high", "medium", "low"]

# 팀 함수 get_advisories() 는 호출할 때마다 advisories_response.json 을 덮어쓴다.
# 미리보기에서 팀 파일이 바뀌지 않도록, 이 앱 안에서만 저장 기능을 꺼 둔다.
advisory_module.make_response_json = lambda data: None


# ---------------------------------------------------------------
# 1. 데이터 읽기
# ---------------------------------------------------------------
def load_mock(file_name):
    """mock json 파일 하나를 읽어 리스트로 돌려준다. 실패하면 빈 리스트."""
    path = f"{MOCK_DIR}/{file_name}"
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as e:
        print("mock load error > ", path, e)
        return []


# 화면이 기억하는 상태 (서버를 끄면 초기화된다)
STATE = {
    "news": load_mock("advisories_mock.json"),   # 카드로 보여줄 공지
    "news_source": "mock",                          # "mock" 또는 "live"
    "fetched_at": None,
    "message": "mock 공지를 보여주고 있습니다. 버튼을 누르면 GitHub 에 실제로 요청합니다.",
}


# ---------------------------------------------------------------
# 2. 버전 비교 : processor.py 의 version_matches_range 를 복사
#    (원본이 다른 함수 안에 있어서 import 할 수 없음 → 임시 복사)
# ---------------------------------------------------------------
def version_matches_range(version, version_range):
    if not isinstance(version, str) or not isinstance(version_range, str):
        return False
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version.strip()) is None:
        return False

    installed = tuple(map(int, version.strip().split(".")))
    for condition in version_range.split(","):
        match = re.fullmatch(r"\s*(<=|>=|==|!=|<|>|=)?\s*([0-9]+(?:\.[0-9]+)*)\s*", condition)
        if match is None:
            return False
        operator, boundary = match.groups()
        limit = tuple(map(int, boundary.split(".")))
        length = max(len(installed), len(limit))
        current = installed + (0,) * (length - len(installed))
        limit += (0,) * (length - len(limit))
        comparisons = {
            "<": current < limit, "<=": current <= limit,
            ">": current > limit, ">=": current >= limit,
            "=": current == limit, "==": current == limit, "!=": current != limit,
        }
        if not comparisons[operator or "=="]:
            return False
    return True


def has_package_info(advisories):
    """공지 목록에 패키지 이름·버전 범위가 들어 있는지 확인"""
    return any(a.get("package_name") and a.get("package_version_range") for a in advisories)


# ---------------------------------------------------------------
# 3. 영향 분석 : 공지 × 서비스 패키지 비교
# ---------------------------------------------------------------
def analyze(advisories, services, packages):
    service_by_page = {s["page_id"]: s for s in services}
    results = []
    for advisory in advisories:
        for package in packages:
            same_package = (advisory.get("package_name") == package.get("package_name")
                            and advisory.get("ecosystem") == package.get("ecosystem"))
            if not same_package:
                continue
            if not version_matches_range(package.get("package_version"), advisory.get("package_version_range")):
                continue
            service = service_by_page.get(package["service_id"][0], {})
            results.append({
                "advisory_id": advisory.get("id"),
                "advisory_url": advisory.get("url"),
                "severity": (advisory.get("severity") or "unknown").lower(),
                "service_name": service.get("resource_name", "알 수 없음"),
                "importance": service.get("business_importance", "-"),
                "package_name": package.get("package_name"),
                "installed_version": package.get("package_version"),
                "package_version_range": advisory.get("package_version_range"),
            })

    importance_rank = {"High": 0, "Medium": 1, "Low": 2}
    results.sort(key=lambda r: (SEVERITY_ORDER.index(r["severity"]) if r["severity"] in SEVERITY_ORDER else 9,
                                importance_rank.get(r["importance"], 9)))
    return results


def build_page_data():
    services = load_mock("service_mock.json")
    packages = load_mock("service_package_mock.json")
    news = STATE["news"]

    # 영향 분석에 쓸 공지 : 패키지 정보가 있으면 가져온 공지, 없으면 mock 공지
    if has_package_info(news):
        analysis_advisories, analysis_source = news, STATE["news_source"]
    else:
        analysis_advisories, analysis_source = load_mock("advisories_mock.json"), "mock"

    results = analyze(analysis_advisories, services, packages)

    # 공지 카드에 "우리 서비스 영향" 표시를 붙이기 위한 집합
    hit_ids = {r["advisory_id"] for r in results}
    # 공지 카드 : mock 은 "공지 1건 × 영향 패키지 범위" 마다 한 줄이라 같은 ID 가 여러 번 나온다.
    #            → 공지 ID 기준으로 한 장의 카드로 묶고, 패키지·범위는 목록으로 모은다.
    cards_by_id = {}
    for a in news:
        card = cards_by_id.get(a.get("id"))
        if card is None:
            card = {
                "id": a.get("id"),
                "title": a.get("title") or a.get("id"),
                "url": a.get("url"),
                "severity": (a.get("severity") or "unknown").lower(),
                "published": (a.get("published_at") or "")[:10],
                "cve_id": a.get("cve_id") or "-",
                "cvss_score": a.get("cvss_score"),
                "reason": a.get("reason") or "-",
                "affects_us": a.get("id") in hit_ids,
                "packages": [],
            }
            cards_by_id[card["id"]] = card
        if a.get("package_name"):
            card["packages"].append(f'{a.get("ecosystem")} / {a.get("package_name")} : {a.get("package_version_range")}')
    cards = list(cards_by_id.values())
    for c in cards:
        c["package_name"] = c["packages"][0].split(" / ")[1].split(" : ")[0] if c["packages"] else "-"
    # 우리에게 영향 있는 공지 먼저, 그다음 심각도 순
    cards.sort(key=lambda c: (not c["affects_us"],
                              SEVERITY_ORDER.index(c["severity"]) if c["severity"] in SEVERITY_ORDER else 9))

    # 서비스별 처리 결과
    hits_by_service = Counter(r["service_name"] for r in results)
    worst_by_service = {}
    for r in results:
        cur = worst_by_service.get(r["service_name"])
        if cur is None or SEVERITY_ORDER.index(r["severity"]) < SEVERITY_ORDER.index(cur):
            worst_by_service[r["service_name"]] = r["severity"]
    pkg_count = Counter(p["service_id"][0] for p in packages)
    service_rows = []
    for s in services:
        name = s["resource_name"]
        service_rows.append({
            "name": name,
            "domain": s.get("business_domain", "-"),
            "importance": s.get("business_importance", "-"),
            "packages": pkg_count[s["page_id"]],
            "hits": hits_by_service[name],
            "worst": worst_by_service.get(name),
        })
    service_rows.sort(key=lambda s: -s["hits"])

    severity_count = Counter(r["severity"] for r in results)
    severity_chart = {
        "labels": [s for s in SEVERITY_ORDER if severity_count[s]],
        "values": [severity_count[s] for s in SEVERITY_ORDER if severity_count[s]],
    }
    service_chart = {
        "labels": [s["name"] for s in service_rows],
        "values": [s["hits"] for s in service_rows],
        "importance": [s["importance"] for s in service_rows],
    }
    summary = {
        "news": len(cards),               # 중복을 묶은 실제 공지 수
        "news_rows": len(news),
        "services": len(services),
        "packages": len(packages),
        "matches": len(results),
        "affected_services": len(hits_by_service),
        "critical_high": severity_count["critical"] + severity_count["high"],
    }
    status = {
        "news_source": STATE["news_source"],
        "analysis_source": analysis_source,
        "fetched_at": STATE["fetched_at"],
        "message": STATE["message"],
    }
    return dict(summary=summary, cards=cards, service_rows=service_rows, results=results,
                severity_chart=severity_chart, service_chart=service_chart, status=status)


# ---------------------------------------------------------------
# 4. Flask 라우트
# ---------------------------------------------------------------
app = Flask(__name__)


@app.get("/")
def preview():
    return render_template("preview.html", **build_page_data())


@app.post("/fetch")
def fetch_advisories():
    """버튼 → 시원님의 get_advisories() 로 GitHub 에 실제 요청"""
    live = advisory_module.get_advisories()
    STATE["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if live:
        STATE["news"], STATE["news_source"] = live, "live"
        if has_package_info(live):
            STATE["message"] = f"GitHub 에서 최신 공지 {len(live)}건을 가져와 영향 분석까지 반영했습니다."
        else:
            STATE["message"] = (f"GitHub 에서 최신 공지 {len(live)}건을 가져왔습니다. "
                                "응답에 패키지·버전 범위가 아직 없어 영향 분석은 mock 공지 기준입니다.")
    else:
        STATE["message"] = "가져오기에 실패했습니다 (네트워크 또는 요청 제한). 기존 목록을 유지합니다. 터미널 로그를 확인하세요."
    return redirect(url_for("preview"))


@app.post("/reset")
def reset():
    STATE.update(news=load_mock("advisories_mock.json"), news_source="mock", fetched_at=None,
                 message="mock 공지로 되돌렸습니다.")
    return redirect(url_for("preview"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)