## 중요!!!! 형상관리 방법
1. 개인 브랜치 제작(1회성)
    git switch -c [원하는 브랜치명]
2. 개인 브랜치에서 작업 후 커밋
    git add .
    git commit -m "작업 내용"
    git push
3. main 으로 이동해 fetch & pull
    git switch main
    git fetch origin
    git pull origin main
4. main 내용을 개인 브랜치로 merge
    git switch [개인 브랜치명]
    git merge main
5. 개인브랜치 충돌 해소 후 커밋, 푸쉬 (공동 작업자 소스 지우지 말고 물어볼 것!)
6. main 으로 머지
    git switch main
    git merge [원하는 브랜치명]
    git push origin main

## 프로젝트 로컬 구동

```bash
## git bash
git clone https://github.com/Shielders35-Python8/python-project.git
cd python-project

# window
python -m venv .venv
.venv\Scripts\activate

# mac or linux
python3 -m venv .venv
source .venv/bin/activate


pip install requests
pip install python-dotenv
pip install -r requirements.txt

python main.py

```

## 슬랙 알림

프로젝트 루트의 `.env`에 [Slack Incoming Webhook](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)
URL을 설정합니다. 해당 웹훅에 연결된 채널로 알림이 전송됩니다.

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/여기에_발급받은_웹훅_경로
```

다음 알림은 해당 작업이 실행되면 자동으로 전송됩니다.

| 상황 | 알림 내용 |
| --- | --- |
| `get_advisories()` 수집 성공 | GitHub 보안 공지 수집 건수. 정상 응답이 0건이어도 전송 |
| `evaluate_impact()` 분석 및 Notion 반영 완료 | 분석 기간, 공지·검사 패키지·취약점 일치·영향 패키지 수 |
| 서버/작업 오류 | GitHub 요청의 각 실패 시도, 파싱·파일 저장, Notion 연결·조회·저장, 설정 로딩 오류 |
| 웹/프로세스 오류 | Flask 미처리 예외, HTTP 5xx 응답, ERROR 이상 로그, 메인·백그라운드 스레드 미처리 예외 |

`main.py`, 기본 웹 서버, 미리보기 서버에 오류 알림이 연결되어 있습니다.
같은 예외가 작업 함수 → 웹 서버 → 로그로 전달되어도 전송은 한 번만 시도합니다.
일반적인 4xx 웹 응답과 사용자의 정상 종료(Ctrl+C)는 서버 오류로 알리지 않습니다.
슬랙 전송 자체의 실패는 로컬 로그로만 남겨 재귀 알림을 방지합니다.
알림에서 환경변수의 토큰·비밀키·비밀번호·웹훅 값은 가립니다.

미리보기 서버는 `/fetch` 수집 성공 후 mock 서비스·패키지 기준의 분석 완료도 알립니다.
이 알림에는 미리보기임을 표시하며, 단순 페이지 조회나 새로고침에는 완료 알림을 보내지 않습니다.
실제 분석의 완료 알림은 모든 Notion 업데이트가 성공한 뒤에만 전송합니다.
알림 연결이 작업을 새로 예약하거나 웹 대시보드의 실행 기능을 구현하지는 않습니다.

서버 프로세스가 강제 종료되거나 Slack/네트워크가 중단되면 전송을 보장할 수 없습니다.
테스트는 외부 서비스를 모의 처리하여 실제 채널 메시지나 Notion 데이터를 만들지 않습니다.

```bash
python -B -m unittest discover -s tests -v
```

```python
from source.common.slack.slack import send_error_message, send_task_message

send_task_message("취약점 분석을 시작합니다.", task_name="취약점 분석")
send_task_message("취약점 분석이 완료되었습니다.", task_name="취약점 분석")

# 작업의 except 블록에서 잡은 예외를 error 인자로 전달할 수 있습니다.
send_error_message(
    "취약점 분석에 실패했습니다.",
    error=RuntimeError("분석 데이터 조회 실패"),
    task_name="취약점 분석",
)
```

`task_name`과 `error`는 생략할 수 있습니다. 전송 성공 시 `True`, 설정 누락이나
전송 실패 시 로그를 남기고 `False`를 반환합니다. 빈 메시지 또는 문자열이 아닌
메시지는 `ValueError`를 발생시킵니다. 각 요청의 타임아웃은 10초이며 자동 재시도는
하지 않습니다.

## 웹 대시보드 실행

가상환경을 활성화한 뒤 **프로젝트 루트**에서 실행합니다.

```bash
python -m pip install -r requirements.txt
python -m source.web.app
```

브라우저에서 http://127.0.0.1:5000 에 접속합니다. 종료는 `Ctrl+C`입니다.
`python source/web/app.py`로 직접 실행할 수도 있습니다.

코드 수정 시 자동으로 재시작하는 개발 모드는 다음과 같습니다.

```bash
python -m flask --app source.web.app run --debug
# 다른 포트가 필요하면 --port 5001 추가
```

웹 구성은 [Flask 공식 Quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)의
라우트·템플릿·정적 파일 구조를 따릅니다.

```text
source/web/
├── app.py                  # Flask 앱 생성, 화면 및 API 라우트
├── templates/index.html    # 대시보드 화면 (Jinja2)
└── static/css/style.css    # 대시보드 스타일
```

| 경로 | 메서드 | 용도 |
| --- | --- | --- |
| `/` | GET | 실행 상태와 분석 결과를 표시할 기본 화면 |
| `/results` | GET | 저장된 패키지 취약도 목록 및 취약도 필터 |
| `/advisories` | GET | Notion 공지의 심각도·생태계·게시 추이·패키지별 통계 |
| `/api/advisories/analysis` | GET | 공지 분석 통계 JSON 및 게시일 기간 필터 |
| `/api/health` | GET | 웹 서버 응답 확인 |
| `/api/results` | GET | Notion에 저장된 서비스 패키지 취약도 조회 및 취약도 필터 |
| `/api/run` | POST | 실행 연결 지점. 현재 HTTP 501과 `not_implemented` 반환 |

대시보드와 분석 결과는 Notion에 저장된 서비스 패키지 취약도를 조회하며,
공지 분석 탭은 저장된 공지 데이터를 집계합니다. 실행 버튼은 비활성 상태로,
GitHub 공지 수집·서비스 영향 평가·DB 저장을 연결하는 작업 실행 기능은 아직 제공하지 않습니다.
기존 대시보드에서 조회하지 못한 값은 `—`로 표시합니다.

분석 결과 탭에서 전체·critical·high·medium·low·safe·미설정/기타를 선택할 수 있습니다.
필터는 목록 전체에 적용한 뒤 50개씩 표시하며, 페이지 이동과 새로고침에도 유지됩니다.
`/results?severity=high`와 `/api/results?severity=high`처럼 같은 조건으로 조회할 수 있습니다.
`severity`는 `all`, `critical`, `high`, `medium`, `low`, `safe`, `unknown`을 지원하며,
생략하거나 잘못된 값을 전달하면 전체를 표시합니다. `unknown`은 빈 값과 그 외 저장 상태를 포함합니다.
API의 `results`와 `filtered_count`는 선택한 조건의 결과이며, `package_count`와
`severity_counts`는 전체 저장 데이터 기준입니다. 조회 실패 시 건수는 `null`로 반환합니다.

## 공지 분석 대시보드

상단 **공지 분석** 탭(`/advisories`)에서 Notion의 advisories 데이터를 조회하고
심각도 분포, 생태계별 공지 수, 게시 추이, 공지가 많은 패키지 상위 10개를 표시합니다.
기존 Notion 인증 설정과 `NOTION_ADVISORIES_DATA_SOURCE_ID`를 사용합니다.
페이지 조회 및 새로고침마다 현재 저장 데이터를 읽으며, 공지 수집이나 DB 수정은 하지 않습니다.

- 시작일·종료일은 게시일(UTC) 기준이며 양쪽 경계를 포함합니다. 비워두면 전체 기간입니다.
- 전체 공지·심각도·추이는 GHSA ID별로 중복을 제거합니다. ID가 없으면 Notion 페이지별로 집계합니다.
- 동일 공지의 심각도가 다르면 가장 높은 알려진 등급, 게시일이 다르면 가장 이른 유효 날짜를 사용합니다.
- 생태계별·패키지별 수는 해당 항목에 연결된 서로 다른 공지 수입니다. 패키지는 생태계와 이름을 함께 구분합니다.
- 게시 추이는 62일 이내일 때 일별, 24개월 이내일 때 월별, 그보다 길면 연도별로 표시하며 공지 없는 구간도 0건으로 채웁니다.
- 심각도 미확인 공지도 포함합니다. 게시일이 없는 공지는 전체 통계에 포함하지만 추이·기간 필터에서는 제외하고 그 수를 안내합니다.
- 빈 DB·기간 내 결과 없음·조회 실패를 구분해 표시합니다. 조회 실패에 샘플 데이터를 대신 표시하지 않습니다.

`source/services/advisory_analysis.py`의 `analyze_advisories(rows, started_at=None, ended_at=None)`는
조회된 행 목록을 집계하는 순수 함수입니다. 날짜 인자는 키워드로 전달합니다.
`source/web/app.py`의 `get_saved_advisory_analysis()`는 Notion 조회와 집계를 연결합니다.
동일한 결과는 `GET /api/advisories/analysis`로 받을 수 있습니다.

```text
/advisories?started_at=2026-09-01&ended_at=2026-09-30
/api/advisories/analysis?started_at=2026-09-01&ended_at=2026-09-30
```

잘못된 기간 입력은 HTTP 400, Notion 조회 실패는 HTTP 503을 반환합니다.
차트는 HTML/CSS로 렌더링하여 외부 차트 라이브러리나 CDN 없이 동작하며,
게시 추이의 수치는 펼쳐지는 표에서도 확인할 수 있습니다.

# 🛡️ **SK Shieldus Rookies Mini Project**

> 
> 
> 
> ### Python Team 8
> 
> 김기현, 노유성, 엄동규, 이시원, 조성현
> 

---

## 주제 :

> 
> 

---

## 프로젝트 개요

### 핵심 기능

### 프로젝트 구조

```bash
security-news/
├── main.py                     # main 실행
├── config/                     # 환경변수 기반 설정
├── ├── config.py               # config.json 의 내용을 꺼내는 메소드
├── └── config.json             # api endpoint 등 공개되어도 무방한 config
├── state.py                    # 중복 알림 방지용 상태 저장/로드
├── sources/
│   └── exmaple.py              # 구조 설명용 파일
├── requirements.txt
├── .gitignore
└── .env
```

---

## 참고 자료

### 공식 문서
https://docs.github.com/en/rest/security-advisories/global-advisories

- 

### 기술 자료

- 

---

