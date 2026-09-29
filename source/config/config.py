import os
import json
from dotenv import load_dotenv

load_dotenv()


def get_config(key):

    # 폴더 경로는 실행 파일인 main 기준
    with open("source/config/config.json", "r", encoding="utf-8") as file:
        try:
            config_data = json.load(file)
            return config_data.get(key)
        except Exception as e:
            print("Config Load Error >> ", e)


def get_env(key: str) -> str:
    return os.environ[key]
