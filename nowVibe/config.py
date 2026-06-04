import os
from datetime import datetime

# Flask 설정
DEBUG = True
SECRET_KEY = 'nowvibe_secret_key_2026'

# 데이터베이스 설정
DB_PATH = os.path.join(os.path.dirname(__file__), 'nowvibe.db')

# API 설정
BASE_URL = '/api'

# 페이지네이션
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

# 메시지 설정
MESSAGE_MAX_LENGTH = 100

# TTL 옵션 (시간)
TTL_OPTIONS = [3, 24, 999]  # 3시간, 24시간, 영구

# Rate Limiting (초 단위)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MESSAGE_CREATE = 3  # 1분에 3개
RATE_LIMIT_GENERAL = 60  # 1분에 60개

# 캠퍼스 설정 (DB 초기화 시)
DEFAULT_CAMPUSES = [
    {"name": "충북대 메인캠퍼스", "latitude": 36.6285, "longitude": 127.4568, "radius_meters": 5000},
]
