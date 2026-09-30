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
| `/api/health` | GET | 웹 서버 응답 확인 |
| `/api/results` | GET | 결과 조회 연결 지점. 현재 `not_connected`와 빈 목록 반환 |
| `/api/run` | POST | 실행 연결 지점. 현재 HTTP 501과 `not_implemented` 반환 |

현재는 웹 기본 구성만 제공합니다. 실행 버튼은 비활성 상태이며 공지 수집·분석·저장은
자동 실행되지 않습니다. `app.py`의 TODO 위치에 실행 및 조회 함수를
연결하고, 화면에 전달할 결과는 `source/processor.py`의 반환 형식을 사용합니다.
화면의 미집계 값은 `—`로 표시합니다.

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

