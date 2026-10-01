# 🛡️ SK Shieldus Rookies Mini Project

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10 이상">
  <img src="https://img.shields.io/badge/Flask-3.1%2B-455A64?style=flat-square&amp;logo=flask&amp;logoColor=white" alt="Flask 3.1 이상, 4.0 미만">
  <img src="https://img.shields.io/badge/Jinja2-Templates-B41717?style=flat-square&amp;logo=jinja&amp;logoColor=white" alt="Jinja2 Templates">
  <img src="https://img.shields.io/badge/Web-HTML%20%C2%B7%20CSS%20%C2%B7%20JS-D4A72C?style=flat-square" alt="HTML, CSS, JavaScript">
  <img src="https://img.shields.io/badge/GitHub-Advisories-2D5347?style=flat-square&amp;logo=github&amp;logoColor=white" alt="GitHub Security Advisories">
  <img src="https://img.shields.io/badge/Notion-Database-52796F?style=flat-square&amp;logo=notion&amp;logoColor=white" alt="Notion Database">
  <img src="https://img.shields.io/badge/Slack-Alerts-4A154B?style=flat-square" alt="Slack Alerts">
</p>

### 보안 권고 수집 · 서비스 패키지 취약도 분석 대시보드

GitHub Security Advisories(보안 권고, 화면에서는 "보안 공지"로 표기)에서 패키지 보안 취약점 공지를 수집해 Notion에 저장하고, 서비스에서 사용 중인 패키지 버전과 비교해 취약도를 판정하는 프로젝트입니다. Flask 웹 대시보드에서 수집, 분석, 결과 조회와 취약 근거 확인을 진행할 수 있습니다.

**Python Team 8** · 김기현 · 노유성 · 엄동규 · 이시원 · 조성현

1. **수집** — GitHub Security Advisories API에서 패키지 보안 취약점 공지를 수집
2. **저장 · 판정** — Notion 데이터베이스에 저장하고, Python으로 서비스별 패키지 버전과 비교해 취약도를 판정하고 통계를 집계
3. **시각화** — Flask와 HTML로 웹 대시보드에 표시
4. **반영 · 알림** — 분석 결과는 Notion에 저장하고, 작업 완료·오류 알림은 Slack으로 전송

| 구성 | 기술 |
| --- | --- |
| 서버 | Python · Flask |
| 화면 | Jinja2 · HTML · CSS · JavaScript (외부 차트 라이브러리 없음) |
| 공지 수집 | GitHub Security Advisories API |
| 데이터 저장 | Notion API (`notion-client`) |
| 버전 비교 | `packaging` · `semver` · `univers` |
| 작업·오류 알림 | Slack Incoming Webhook |

---

## 목차

- [빠른 시작](#빠른-시작)
- [실행 방법](#실행-방법)
- [대시보드 사용](#대시보드-사용)
- [API 안내](#api-안내)
- [Slack 알림](#slack-알림)
- [프로젝트 구조](#프로젝트-구조)
- [개발 및 협업](#개발-및-협업)
- [참고 자료](#참고-자료)

## 빠른 시작

Python **3.10 이상**과 Git이 필요합니다. 아래 명령은 프로젝트 루트에서 실행합니다.

### 1. 저장소 내려받기

```bash
git clone https://github.com/Shielders35-Python8/python-project.git
cd python-project
```

### 2. 가상환경과 의존성 준비

**Windows · PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

<details>
<summary>macOS / Linux 또는 Windows Git Bash에서 실행하기</summary>

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows · Git Bash**

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

</details>

### 3. 환경변수 설정

처음 설정할 때 [.env.example](.env.example)을 복사해 프로젝트 루트에 `.env`를 만들고 값을 입력합니다. 이미 `.env`가 있다면 필요한 항목만 추가합니다.

```powershell
Copy-Item .env.example .env
```

macOS / Linux / Git Bash에서는 `cp .env.example .env`를 사용합니다.

| 환경변수 | 용도 |
| --- | --- |
| `GITHUB_TOKEN` | GitHub API 인증. 설정하면 인증된 요청으로 공지를 수집 |
| `NOTION_TOKEN` | Notion 데이터 조회·저장 인증 |
| `NOTION_ADVISORIES_DATA_SOURCE_ID` | 보안 공지 데이터 소스 |
| `NOTION_SERVICE_DATA_SOURCE_ID` | 관리 서비스 데이터 소스 |
| `NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID` | 서비스 패키지 및 저장된 취약도 데이터 소스 |
| `SLACK_WEBHOOK_URL` | 작업·오류 알림을 받을 Slack 웹훅 |
| `NOTION_PARENT_PAGE_ID` | Notion 데이터베이스를 생성할 때 사용할 부모 페이지 ID |

서비스 관련 두 항목은 현재 `.env.example`에 없으므로 **대시보드 사용 시 `.env`에 직접 추가**합니다.

```dotenv
NOTION_SERVICE_DATA_SOURCE_ID=서비스_데이터_소스_ID
NOTION_SERVICE_PACKAGE_DATA_SOURCE_ID=서비스_패키지_데이터_소스_ID
```

Notion 조회에는 **데이터 소스 ID**를 사용합니다. 데이터베이스 ID와 구분해 입력하고, 대상 데이터에 연동이 접근할 수 있도록 설정합니다. 데이터 구조는 [스키마 정의](source/databases/schemas/)를 참고하세요. `.env`는 Git에서 제외됩니다.

### 4. 대시보드 실행

```bash
python -m flask --app source.web.app run
```

브라우저에서 **[http://127.0.0.1:5000](http://127.0.0.1:5000)**에 접속합니다. 종료할 때는 실행한 터미널에서 `Ctrl+C`를 누릅니다.

## 실행 방법

가상환경을 활성화한 상태에서 사용합니다.

| 실행 방식 | 명령 |
| --- | --- |
| Flask CLI | `python -m flask --app source.web.app run` |
| 코드 변경 시 자동 재시작 | `python -m flask --app source.web.app run --debug` |
| 다른 포트 사용 | `python -m flask --app source.web.app run --port 5001` |
| Python 모듈 직접 실행 | `python -m source.web.app` |
| Python 파일 직접 실행 | `python source/web/app.py` |

`--app source.web.app`은 [웹 앱 모듈](source/web/app.py)을 지정하는 **이번 실행의 인자**입니다. 이 명령만으로 설정 파일이 생성되거나 수정되지는 않습니다.

<details>
<summary>PowerShell에서 <code>flask run</code>만 사용하고 싶다면</summary>

```powershell
$env:FLASK_APP = "source.web.app"
flask run
```

환경변수는 현재 PowerShell 세션에서 유지됩니다.

</details>

`python main.py`는 현재 시작 문구만 출력합니다. 수집 함수 호출은 주석 처리되어 있으므로, 웹 기능을 사용하려면 위의 대시보드 실행 명령을 사용하세요. 서버 시작 자체는 공지 수집이나 분석을 실행하지 않습니다.

## 대시보드 사용

```text
신규 공지 가져오기 → GitHub 수집 → Notion 저장
분석 실행        → 저장된 공지와 서비스 패키지 비교 → Notion 취약도 반영
결과 확인        → 분석 결과 · 공지 통계 · 취약 근거 조회
```

### 화면 구성

| 메뉴 | 경로 | 주요 내용 |
| --- | --- | --- |
| 대시보드 | `/` | 공지·서비스·패키지 요약과 공지 통계 |
| 보안 공지 | `/advisories/list` | 저장된 공지, 패키지별 취약 버전 범위, 게시일·갱신일 |
| 공지 분석 | `/advisories` | 심각도·생태계·게시 추이·패키지별 통계와 기간 필터 |
| 실행 상태 | `/run-status` | 분석 실행, 진행 단계, 최근 실행 기록 |
| 분석 결과 | `/results` | 서비스명으로 표시한 패키지 취약도와 서비스·심각도 필터 |
| 취약 근거 | `/evidence` | 일치한 공지, 판정 불가 사유, 현재 비교 결과와 저장값의 차이 |
| 프로젝트 가이드 | `/guide` | 프로젝트 설명 페이지 |

### 공지 수집

대시보드 또는 보안 공지 화면에서 시작일·종료일을 지정하고 **신규 공지 가져오기**를 누릅니다.

- 기간은 GitHub **게시일(UTC)** 기준이며 양 끝 날짜를 포함합니다. 기본값은 오늘을 포함한 최근 7일입니다.
- 해당 기간의 **검토 완료(reviewed)** 공지를 갱신일 내림차순으로 **최대 100건** 가져옵니다. 전체 페이지 수집은 지원하지 않습니다.
- 공지 하나에 패키지가 여러 개면 Notion 구조에 맞춰 **첫 번째 패키지와 첫 번째 CWE**만 저장합니다.
- 수집 → 중복 확인 → Notion 저장 단계와 수집·제외·저장·실패 건수를 표시합니다.
- GitHub 요청 실패와 정상 응답 0건을 구분합니다. 일부 저장 실패는 별도로 표시하며 같은 기간으로 재시도할 수 있습니다.
- GitHub 요청은 서버·네트워크 오류를 최대 3회 재시도하고, 400·401·403·404는 연동 정보 확인이 필요하므로 바로 중단합니다. 재시도 중에는 로그만 남기고 최종 실패만 Slack으로 알립니다.
- 작업 완료·실패 후 공지 조회 캐시를 갱신합니다. 패키지 취약도 판정은 이어서 **분석 실행**으로 진행합니다.

<details>
<summary>Notion 중복 확인 및 갱신 기준</summary>

Notion은 고유키(UNIQUE) 제약이 없어 같은 기간을 다시 수집하면 같은 공지가 중복 저장될 수 있습니다. [sync_advisories_to_notion()](source/services/advisory_sync.py)은 저장 전에 이번에 수집한 공지 **ID로만** Notion을 조회하고(100개씩 묶어 `or` 조건으로 요청), 게시일·갱신일을 비교해 처리를 나눕니다.

| Notion 상태 | 처리 |
| --- | --- |
| 같은 ID의 행이 없음 | 새 행으로 저장 |
| 같은 ID, `published_at`·`updated_at`도 같음 | 이미 저장된 공지로 보고 제외 |
| 같은 ID, `published_at`이나 `updated_at`이 다르거나 비어 있음 | 새로 만들지 않고 기존 행을 GitHub 값으로 수정 |
| 같은 ID의 행이 여러 개 | 하나만 남기고 나머지는 Notion 휴지통으로 이동 |

같은 ID의 행이 여러 개일 때 남길 행은 ① 두 날짜가 GitHub과 모두 같은 행 ② 두 날짜가 모두 채워진 행 ③ 조회 순서상 첫 행 순으로 고릅니다. 삭제는 날짜가 비어 있거나 다른 행부터 진행하며, 삭제 건수는 서버 로그에만 남깁니다.

- 날짜는 GitHub(`...Z`)과 Notion(`...+00:00`) 형식을 맞춘 뒤 UTC 분 단위로 비교합니다.
- 수정할 때는 저장하는 11개 컬럼을 모두 GitHub 값으로 덮어씁니다. GitHub의 갱신일은 저장하지 않는 필드(설명, 참고 링크, CVSS 등)가 바뀌어도 갱신되므로, 화면에서는 `updated_at`만 바뀐 것처럼 보일 수 있습니다.
- ID가 없는 공지는 식별할 수 없어 제외합니다. Notion 조회가 실패하면 중복 적재를 막기 위해 저장을 진행하지 않습니다.
- Notion은 롤백을 지원하지 않으므로 도중에 실패해도 이미 저장된 행은 유지됩니다. 같은 기간으로 다시 실행하면 저장된 공지는 제외되어 안전하게 재시도할 수 있습니다.

</details>

### 취약도 분석과 결과

**분석 실행**은 Notion에 저장된 전체 공지와 서비스 패키지의 이름·생태계·버전을 비교하고, 판정된 취약도를 Notion에 저장합니다. 화면을 이동해도 작업은 계속되며 조회 → 판정 → 저장 단계와 저장 건수를 확인할 수 있습니다.

| 판정 상황 | 저장 방식 |
| --- | --- |
| 취약점이 여러 개 일치 | `critical > high > medium > low` 중 가장 높은 값을 패키지별로 한 번 저장 |
| 같은 패키지의 버전·범위를 비교할 수 없음 | 확인된 취약점이 없다면 `unknown`으로 저장하고 **알 수 없음** 표시 |
| 확인된 취약점과 판정 불가 공지가 함께 있음 | 확인된 최고 심각도 유지 |
| 기존 `unknown`의 관련 공지를 전체 분석하여 모두 비교 가능·불일치 | `safe`로 갱신하여 이전 판정 불가를 해소 |
| 그 외 모든 비교가 불일치·관련 공지 없음·기간을 제한한 분석 | 기존 취약 판정을 자동으로 해제하지 않음 |

분석 결과는 서비스·취약도·검색 기준과 검색어를 고른 뒤 **검색 버튼 또는 Enter**로 조회합니다. 조건을 함께 적용한 결과를 **50개씩** 표시합니다. 서비스 선택 목록과 표에는 서비스명과 비즈니스 도메인을 함께 표시하며, 도메인 값이 없으면 서비스명만 표시합니다. 취약도별 버튼의 건수는 선택한 서비스와 검색 조건 기준입니다. 서비스 미연결 항목도 따로 볼 수 있습니다. 조건을 바꿔 검색하면 첫 페이지로 이동하고, 페이지 이동과 새로고침에는 모든 조건을 유지합니다.

검색어(`q`)는 앞뒤 공백을 제거하고 대소문자 구분 없이 부분 일치로 검색합니다. 검색 기준(`search_field`)은 전체 항목(`all`), 패키지명(`package_name`), 패키지 ID(`package_id`), 서비스명(`service_name`), 비즈니스 도메인(`business_domain`), 생태계(`ecosystem`) 중 선택합니다. 기준을 생략하거나 잘못된 값을 입력하면 전체 항목을 검색하며, 검색어가 비어 있으면 선택한 서비스·취약도 필터만 적용합니다.

취약도(`severity`)는 `all`, `critical`, `high`, `medium`, `low`, `safe`, `unknown`을 지원합니다. `unknown`에는 판정 불가, 빈 값과 기타 저장 상태가 포함됩니다. 취약도를 생략하거나 잘못된 값을 입력하면 전체 취약도를 표시합니다. 서비스(`service`)는 이름 변경·중복에 영향받지 않도록 내부적으로 Notion 서비스 페이지 ID를 사용하며, 생략하면 전체 서비스, `unlinked`는 서비스 미연결 항목입니다. 존재하지 않는 서비스 값은 전체로 바꾸지 않고 결과 0건으로 표시합니다.

**취약 근거** 화면은 저장된 공지와 패키지를 다시 비교해 근거를 보여주는 읽기 전용 화면입니다. 근거 있음·판정 불가·저장값과 다름·전체 필터와 서비스·검색 조건을 제공하며, 이 화면을 조회해도 Notion 데이터는 수정되지 않습니다.

<details>
<summary>분석 범위와 실행 상태 상세</summary>

- [evaluate_impact(None, None)](source/services/processor.py)는 저장된 전체 공지를 분석합니다. 함수에 날짜를 전달하면 `updated_at` 기간을 적용하지만, 웹 실행 API는 기간·신규 수집 옵션을 받지 않습니다.
- 버전 비교는 [version_comparison.py](source/services/version_comparison.py)에서 쉼표로 연결한 `<`, `<=`, `>`, `>=`, `=`, `==`, `!=` 조건을 모두 만족하는지 확인합니다. `≥`, `≤`, `≠`도 지원합니다. `processor.py`의 분석 저장과 취약 근거 화면은 같은 함수를 사용합니다.
- 등록된 13개 생태계를 모두 처리합니다. pip/PyPI는 `packaging`의 PEP 440, NuGet·Maven·RubyGems는 [`univers`](https://github.com/aboutcode-org/univers)의 전용 비교기를 사용합니다. NuGet의 네 번째 숫자·대소문자 무시, Maven의 `Final`·`GA`·`RELEASE` 별칭, RubyGems의 점으로 구분한 사전 릴리스도 반영합니다.
- npm·Go·Rust·Erlang·GitHub Actions·Swift는 `semver`로 비교하며, `v` 접두사와 Go의 pseudo-version을 처리합니다. Composer는 `dev < alpha < beta < RC < stable < patch` 순서를, Pub은 빌드 식별자까지 비교하는 고유 규칙을 적용합니다. 생태계 이름의 대소문자와 PyPI/pip, Cargo/rust, Hex/erlang 등의 별칭도 정규화합니다.
- `other`와 미등록 생태계도 숫자·점 또는 SemVer 표기라면 비교합니다. 순서를 정의할 수 없는 임의 태그·브랜치·커밋 해시, 빈 값, 미지원 범위 문법(`||`, 와일드카드, `^`, `~`, 네이티브 구간 표기)은 판정 불가로 남깁니다. 취약 범위는 사전 릴리스도 명시된 조건으로 판정하며, 패키지 설치 도구의 사전 릴리스 자동 제외 규칙은 적용하지 않습니다.
- 실행 중에는 분석 버튼을 비활성화하고, 중복 실행 요청에 HTTP `409`와 기존 작업을 반환합니다.
- 저장 도중 실패하면 성공으로 표시하지 않습니다. 이미 저장된 건수와 실패 안내를 남기고 조회 캐시를 갱신합니다.
- 분석 상태와 최근 **20건**의 기록은 서버 메모리에 보관합니다. 수집 상태도 메모리에 보관하므로 현재 구조는 **단일 서버 프로세스**용입니다.
- 서버 종료·재시작 시 진행 중인 작업이 중단되고 메모리의 상태·기록이 초기화됩니다. Notion에 이미 저장한 데이터는 유지됩니다. 분석 중에는 개발 서버 재시작을 피하세요.
- 웹 분석의 Notion 조회·저장은 대시보드 조회와 요청 간격 및 일시 오류 재시도 정책을 공유합니다. 실행 상태 조회 자체는 Notion을 호출하지 않습니다.

</details>

### 공지 통계와 데이터 갱신

**공지 분석**은 Notion에 저장된 공지를 집계해 심각도 분포, 생태계별 공지 수, 게시 추이, 공지가 많은 패키지 상위 10개를 표시합니다. 시작일·종료일은 게시일(UTC) 기준이고, 비워두면 전체 기간입니다.

조회 데이터는 서버 메모리에서 **60초간 재사용**합니다. 이후 화면에 접속하면 기존 데이터를 먼저 보여주면서 백그라운드에서 갱신합니다. **최신 데이터 새로고침**은 Notion 저장 데이터를 다시 조회하는 기능이며, GitHub 수집은 수집 버튼으로 실행합니다.

| 화면 상태 | 동작 |
| --- | --- |
| 처음 불러오는 중 | 로딩 안내를 표시하고 준비되면 자동으로 다시 표시 |
| 기존 데이터 갱신 중 | 마지막 성공 결과를 먼저 표시 |
| 최신 조회 실패 | 이전 데이터를 유지하고 실패 안내와 데이터 확인 시각 표시 |
| 조회할 수 없는 값 | `—`로 표시. 실제 빈 데이터와 조회 실패를 구분 |

<details>
<summary>공지 통계 집계 기준</summary>

- 전체 공지·심각도·추이는 GHSA ID별로 중복을 제거합니다. ID가 없으면 Notion 페이지별로 집계합니다.
- 동일 공지의 심각도가 다르면 가장 높은 알려진 등급, 게시일이 다르면 가장 이른 유효 날짜를 사용합니다.
- 생태계별·패키지별 수는 해당 항목에 연결된 서로 다른 공지 수입니다. 패키지는 생태계와 이름을 함께 구분합니다.
- 게시 추이는 62일 이내일 때 일별, 24개월 이내일 때 월별, 그보다 길면 연도별로 표시합니다. 공지가 없는 구간도 0건으로 채웁니다.
- 심각도 미확인 공지도 포함합니다. 게시일이 없는 공지는 전체 통계에는 포함하지만 추이·기간 필터에서는 제외하고 건수를 안내합니다.
- 빈 DB, 기간 내 결과 없음, 조회 실패를 구분하며 조회 실패를 샘플 데이터로 대체하지 않습니다.
- 차트는 HTML/CSS로 렌더링해 외부 차트 라이브러리나 CDN 없이 동작합니다. 게시 추이의 수치는 펼쳐지는 표에서도 확인할 수 있습니다.

[analyze_advisories(rows, started_at=None, ended_at=None)](source/services/advisory_analysis.py)는 조회된 행 목록을 집계하는 순수 함수입니다. 날짜는 키워드 인자로 전달합니다. 웹 앱의 `get_saved_advisory_analysis()`가 조회와 집계를 연결합니다.

</details>

<details>
<summary>조회 캐시와 재시도 정책</summary>

- 탭 전환, 기간·취약도 필터, 페이지 이동은 데이터 소스별로 같은 스냅샷을 공유합니다.
- 수동 새로고침은 `refresh=1`을 사용하며 필터·페이지를 유지합니다. 같은 소스의 동시 요청은 한 작업으로 합치고, 5초 이내 연속 클릭은 새 조회를 시작하지 않습니다.
- 갱신 실패 후에는 최소 30초, Notion의 `Retry-After`가 더 길면 해당 시간까지 기다립니다.
- 앱 전체의 Notion 요청 시작 간격은 0.5초 이상이며, 일시적인 오류는 같은 페이지에서 최대 3회 시도합니다. 대시보드 조회 요청의 타임아웃은 15초입니다.
- 캐시는 서버 프로세스별 메모리에 보관해 재시작 시 초기화됩니다. 수집·분석·Notion 저장 작업 자체에는 이 조회 캐시를 적용하지 않습니다.

</details>

## API 안내

### 조회 API

| 메서드 | 경로 | 응답 내용 |
| --- | --- | --- |
| GET | `/api/health` | 웹 서버 응답 확인. 외부 서비스 상태는 포함하지 않음 |
| GET | `/api/advisories` | Notion에 저장된 보안 공지 목록 |
| GET | `/api/advisories/analysis` | 공지 통계와 게시일 기간 필터 |
| GET | `/api/results` | 저장된 패키지 취약도와 서비스·심각도 필터 |
| GET | `/api/cache-status?view=dashboard` | 데이터 준비·갱신 상태. Notion 요청 없음 |
| GET | `/api/run-status` | 현재 분석 단계·건수·최근 실행 기록 |
| GET | `/api/advisories/sync-status` | 최근 수집의 기간·진행 상태·수집·제외·저장·실패 건수 |

조회 예시:

```text
/results?severity=high
/api/results?severity=high
/results?severity=high&search_field=package_name&q=django
/api/results?severity=high&search_field=package_name&q=django
/advisories?started_at=2026-09-01&ended_at=2026-09-30
/api/advisories/analysis?started_at=2026-09-01&ended_at=2026-09-30
```

캐시를 사용하는 JSON API는 최초 데이터 준비 중 HTTP `202`, `status: loading`, `Retry-After: 2`를 반환합니다. 정상·오류 응답에는 `cache` 상태가 포함됩니다. 잘못된 기간은 `400`, Notion 조회 실패는 `503`으로 구분합니다.

분석 결과 API의 `results`와 `filtered_count`는 서비스·취약도·검색 조건을 함께 적용한 기준이며, `package_count`와 `severity_counts`는 전체 저장 데이터 기준입니다. `service_severity_counts`는 선택한 서비스의 취약도별 건수이고, `search_severity_counts`는 여기에 검색 조건도 적용한 취약도별 건수입니다. `service_options`는 서비스 선택 값과 표시 이름 목록입니다. 패키지 조회 실패 시 건수는 `null`로 반환합니다.

### 실행 API

실행 API는 같은 출처의 JSON 요청을 받습니다. 작업을 시작하면 HTTP `202`, 같은 종류의 작업이 이미 실행 중이면 `409`를 반환합니다.

| 메서드 | 경로 | JSON 본문 | 동작 |
| --- | --- | --- | --- |
| POST | `/api/run` | `{}` | 저장된 전체 공지의 취약도 분석 시작 |
| POST | `/api/advisories/sync` | `{"started_at":"2026-09-01","ended_at":"2026-09-30"}` | 지정한 게시일 기간의 공지 수집·Notion 저장 |

수집 요청에는 두 날짜가 모두 필요합니다. 잘못된 날짜나 역전된 기간은 작업 시작 전에 거부합니다.

## Slack 알림

`.env`의 `SLACK_WEBHOOK_URL`에 설정한 **Incoming Webhook과 연결된 채널**로 알림을 전송합니다.

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/여기에_발급받은_웹훅_경로
```

| 상황 | 알림 내용 |
| --- | --- |
| 공지 수집·Notion 적재 완료 | `[작업] 보안 공지 Notion 적재` — 기간, 수집·생성·수정·제외·실패 건수와 실패 사유(최대 5건) |
| 취약도 분석·Notion 반영 완료 | `[작업] 취약도 분석` — 분석 범위, 공지·검사 패키지·취약점 일치·영향 패키지·알 수 없음·판정 불가 해소 건수 |
| 서버·작업 오류 | GitHub 최종 수집 실패, 파싱·파일 저장, Notion 연결·조회·저장, 설정 로딩 오류 |
| 웹·프로세스 오류 | Flask 미처리 예외, HTTP 5xx, ERROR 이상 로그, 메인·백그라운드 스레드 미처리 예외 |

`main.py`와 웹 서버에 오류 알림이 연결되어 있습니다. 알림 기능은 작업을 새로 예약하지 않습니다. 적재 완료 알림은 적재가 끝난 뒤 한 번, 분석 완료 알림은 모든 Notion 업데이트가 성공한 뒤 전송합니다. GitHub 요청을 재시도하는 동안에는 알림을 보내지 않습니다.

<details>
<summary>알림 호출 예시와 전송 정책</summary>

```python
from source.common.slack.slack import send_error_message, send_task_message

send_task_message("취약점 분석을 시작합니다.", task_name="취약점 분석")
send_task_message("취약점 분석이 완료되었습니다.", task_name="취약점 분석")

send_error_message(
    "취약점 분석에 실패했습니다.",
    error=RuntimeError("분석 데이터 조회 실패"),
    task_name="취약점 분석",
)
```

- `task_name`과 `error`는 생략할 수 있습니다. 성공 시 `True`, 설정 누락·전송 실패 시 로그를 남기고 `False`를 반환합니다.
- 빈 메시지나 문자열이 아닌 메시지는 `ValueError`를 발생시킵니다. 전송 타임아웃은 10초이며 자동 재시도는 하지 않습니다.
- 같은 예외가 작업 함수 → 웹 서버 → 로그로 전달되어도 전송은 한 번만 시도합니다.
- 일반적인 HTTP 4xx와 `Ctrl+C` 정상 종료는 서버 오류로 알리지 않습니다. Slack 전송 실패는 로컬 로그만 남깁니다.
- 환경변수의 토큰·비밀키·비밀번호·웹훅 값은 알림에서 가립니다.
- 서버 강제 종료나 Slack·네트워크 중단 시에는 알림 전송을 보장할 수 없습니다.

</details>

## 프로젝트 구조

```text
python-project/
├── main.py                         # 메인 스크립트 · 현재 시작 문구 출력
├── requirements.txt                # Python 의존성
├── .env.example                    # 환경변수 예시
├── source/
│   ├── common/
│   │   ├── github_advisory/         # GitHub 보안 공지 수집
│   │   ├── notion/                  # Notion 클라이언트(notion.py) · 요청 간격·재시도 정책(query_policy.py)
│   │   └── slack/                   # 작업·오류 알림
│   ├── config/                      # 공개 설정 · 환경변수 로딩
│   ├── databases/schemas/           # Notion 데이터 구조
│   ├── example/                     # 예시 데이터 · 서비스 패키지 시드 도구
│   ├── services/
│   │   ├── advisory_sync.py         # 공지 중복 확인 · Notion 적재 · 적재 결과 알림
│   │   ├── advisory_analysis.py     # 공지 통계 집계
│   │   ├── processor.py             # 공지와 패키지 매칭 · 취약도 판정·저장
│   │   └── version_comparison.py    # 생태계별 버전 비교 규칙
│   └── web/
│       ├── app.py                   # Flask 앱 생성 · 화면 및 API 라우트
│       ├── data_cache.py            # 조회 캐시 · 백그라운드 갱신
│       ├── analysis_runs.py         # 분석 실행 상태 · 이력
│       ├── advisory_sync_runs.py    # 공지 수집 실행 상태
│       ├── advisory_list.py         # 공지 목록 구성
│       ├── dashboard_data.py        # 분석 결과 구성 · 필터
│       ├── evidence.py              # 취약 근거 조회 · 비교
│       ├── templates/               # Jinja2 화면 템플릿
│       └── static/                  # CSS · 브라우저용 JavaScript
└── tests/                           # 외부 연동을 모의 처리한 테스트
```

### 화면 파일의 역할

| 파일 | 역할 |
| --- | --- |
| `templates/index.html` | 공통 화면 틀과 대시보드·실행 상태·분석 결과 |
| `templates/advisory_list.html` | 보안 공지 목록 |
| `templates/advisory_analysis.html` | 공지 분석의 기간 필터·요약 통계 |
| `templates/advisory_charts.html` | 대시보드·공지 분석이 공유하는 차트 |
| `templates/advisory_sync.html` | 공지 수집 입력과 진행 상태 |
| `templates/evidence.html` | 취약 근거 전용 화면 |
| `templates/guide.html` | 프로젝트 소개·발표용 안내 화면 (`/guide`) |
| `static/css/style.css` | 대시보드 스타일 |
| `static/js/dashboard-cache.js` | 갱신 상태 확인·자동 새로고침·시간 표시 |
| `static/js/advisory-sync.js` | 공지 수집 요청·진행 상태 표시 |
| `static/js/analysis-run.js` | 분석 실행 요청·진행 상태·이력 표시 |

표의 경로는 `source/web/` 기준입니다. `index.html`은 현재 페이지에 따라 `{% include %}`로 필요한 화면 조각을 포함합니다. Python은 서버의 조회·분석·저장을, JavaScript는 브라우저의 버튼 동작과 상태 갱신을 담당합니다.

## 개발 및 협업

### 테스트

```bash
python -B -m unittest discover -s tests -v
```

외부 서비스를 모의 처리하므로 테스트는 실제 Slack 메시지나 Notion 데이터를 만들지 않습니다.

### 브랜치 작업 순서

개인 브랜치에서 작업한 뒤 최신 `main`을 반영하고 병합합니다. 아래의 `feature/my-work`는 개인 브랜치 이름의 예시입니다.

**1. 개인 브랜치 생성 · 최초 한 번**

```bash
git switch -c feature/my-work
```

**2. 변경 확인 후 커밋·푸시**

```bash
git status
git add .
git commit -m "작업 내용"
git push -u origin feature/my-work
```

**3. 최신 main을 개인 브랜치에 반영**

```bash
git switch main
git fetch origin
git pull origin main
git switch feature/my-work
git merge main
```

충돌이 발생하면 **공동 작업자의 코드를 임의로 지우지 말고 담당자와 확인**합니다. 충돌을 해결한 뒤 해당 변경을 커밋하고 개인 브랜치에 푸시합니다.

**4. main에 병합**

```bash
git switch main
git merge feature/my-work
git push origin main
```

## 참고 자료

- [GitHub REST API · Global Security Advisories](https://docs.github.com/en/rest/security-advisories/global-advisories)
- [Flask · Quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
- [Slack · Incoming Webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)
