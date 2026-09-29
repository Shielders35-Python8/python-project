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

