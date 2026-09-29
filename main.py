"""
    프로젝트 메인 스크립트
"""
import os
from dotenv import load_dotenv
from source.advisories import example_method

def main():
    print("시작했습니다용")
    print(example_method())    

if __name__ == "__main__": 
    main() 