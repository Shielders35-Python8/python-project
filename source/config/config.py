import json, time

def load_config():
    """
        source/config/config.json 의 config 를 조회하는 함수
        config 에는 연동에 필요한 정보를 저장하기 때문에,
        json load 시에 발생하는 에러가 아닐 경우 에러 리턴,
        json load 시에 발생하는 에러일 경우 3회 재시도 실행, 마지막까지 실패면 에러 리턴

        Return: json
    """
    for attempt in range(3):
        try:
            with open("source/config/config.json", "r", encoding="utf-8") as file:
                return json.load(file)

        except (OSError, json.JSONDecodeError):
            # 마지막 시도까지 실패하면 예외를 그대로 발생
            if attempt == 2:
                raise

            time.sleep(0.5)


CONFIG = load_config()


def get_config(key):
    """
        프로젝트 로드 시에 읽어온 Config 에서
        원하는 key 로 config 내용을 뽑아오는 함수
    """
    return CONFIG.get(key)