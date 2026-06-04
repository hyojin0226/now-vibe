import sqlite3
import os
from config import DB_PATH, DEFAULT_CAMPUSES
from datetime import datetime, timedelta

def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id VARCHAR(255) UNIQUE NOT NULL,
            session_id VARCHAR(255),
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_banned BOOLEAN DEFAULT 0
        )
    ''')
    
    # Messages 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text VARCHAR(100) NOT NULL,
            image_url VARCHAR(500),
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name VARCHAR(100),
            ttl INTEGER DEFAULT 3,
            campus_id INTEGER NOT NULL,
            likes_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_deleted BOOLEAN DEFAULT 0,
            deleted_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (campus_id) REFERENCES campuses(id)
        )
    ''')
    
    # Likes 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (message_id) REFERENCES messages(id),
            UNIQUE(user_id, message_id)
        )
    ''')
    
    # Campuses 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_meters REAL DEFAULT 5000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 캠퍼스 데이터 초기화
    cursor.execute('SELECT COUNT(*) FROM campuses')
    if cursor.fetchone()[0] == 0:
        for campus in DEFAULT_CAMPUSES:
            cursor.execute('''
                INSERT INTO campuses (name, latitude, longitude, radius_meters)
                VALUES (?, ?, ?, ?)
            ''', (campus['name'], campus['latitude'], campus['longitude'], campus['radius_meters']))

    # User Locations 테이블 (사용자 위치/동선 기록용)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Reports 테이블 (메시지 신고 기록용 - 중복 신고 방지)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (message_id) REFERENCES messages(id),
            UNIQUE(user_id, message_id)
        )
    ''')

    conn.commit()
    conn.close()
    print(f"✅ 데이터베이스 초기화 완료: {DB_PATH}")

def get_db_connection():
    """데이터베이스 연결"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cleanup_expired_messages():
    """만료된 메시지 자동 삭제"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat() + 'Z'
    cursor.execute('''
        UPDATE messages
        SET is_deleted = 1, deleted_at = ?
        WHERE expires_at IS NOT NULL AND expires_at < ? AND is_deleted = 0
    ''', (datetime.utcnow().isoformat(), now))
    
    conn.commit()
    deleted_count = cursor.rowcount
    conn.close()
    
    if deleted_count > 0:
        print(f"🗑️  {deleted_count}개의 만료된 메시지가 삭제되었습니다.")
    
    return deleted_count
