"""
    프로젝트 메인 스크립트
"""
import os
from dotenv import load_dotenv
from source.advisories import get_advisories, example_method

def main():
    print("시작했습니다용")

    # config 값 꺼내기 테스트용 메소드
    # print(example_method())
    
    # github advisories 호출 및 parsing
    # IP 기준 시간 당 60회 호출 가능하다고 합니다. 필요하지 않은 경우 주석 처리 부탁드립니당
    # 아래 함수의 리턴값의 경우, source/example/advisories_response.json 에 예시 올려두었습니다.
    # get_advisories()

if __name__ == "__main__": 
    main() 