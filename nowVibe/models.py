from database import get_db_connection
from datetime import datetime, timedelta
from config import TTL_OPTIONS
import json
import math

# ==================== USER 관련 함수 ====================

def get_or_create_user(device_id):
    """device_id로 사용자 조회 또는 생성"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE device_id = ?', (device_id,))
    user = cursor.fetchone()
    
    if user:
        # 마지막 활동 시간 업데이트
        cursor.execute('UPDATE users SET last_activity = ? WHERE device_id = ?',
                      (datetime.utcnow().isoformat(), device_id))
        conn.commit()
        user_id = user['id']
    else:
        # 새 사용자 생성
        cursor.execute('''
            INSERT INTO users (device_id, created_at, last_activity)
            VALUES (?, ?, ?)
        ''', (device_id, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
        conn.commit()
        user_id = cursor.lastrowid
    
    conn.close()
    return user_id

def is_user_banned(user_id):
    """사용자 밴 여부 확인"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_banned FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result and result['is_banned'] == 1 if result else False

# ==================== MESSAGE 관련 함수 ====================

def create_message(user_id, text, latitude, longitude, location_name, ttl, campus_id, image_url=None):
    """메시지 생성"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    created_at = datetime.utcnow().isoformat()
    
    # TTL에 따른 만료 시간 계산
    if ttl == 999:
        expires_at = None  # 영구 보존
    else:
        expires_at = (datetime.utcnow() + timedelta(hours=ttl)).isoformat()
    
    cursor.execute('''
        INSERT INTO messages (user_id, text, latitude, longitude, location_name, 
                            ttl, campus_id, image_url, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, text, latitude, longitude, location_name, ttl, campus_id, 
          image_url, created_at, expires_at))
    
    conn.commit()
    message_id = cursor.lastrowid
    conn.close()
    
    return get_message_by_id(message_id)

def get_message_by_id(message_id):
    """ID로 메시지 조회"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM messages
        WHERE id = ? AND is_deleted = 0
    ''', (message_id,))
    
    message = cursor.fetchone()
    conn.close()
    
    return dict(message) if message else None

def get_all_messages(campus_id, page=1, limit=20, sort='latest', device_id=None):
    """모든 메시지 조회 (페이지네이션)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 정렬 기준
    order_by = 'created_at DESC' if sort == 'latest' else 'likes_count DESC'
    
    offset = (page - 1) * limit
    
    # 전체 개수 조회
    cursor.execute('''
        SELECT COUNT(*) as count FROM messages
        WHERE campus_id = ? AND is_deleted = 0
    ''', (campus_id,))
    total = cursor.fetchone()['count']
    
    # 메시지 조회
    cursor.execute(f'''
        SELECT * FROM messages
        WHERE campus_id = ? AND is_deleted = 0
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    ''', (campus_id, limit, offset))
    
    messages = cursor.fetchall()
    
    # 각 메시지에 대해 현재 사용자의 좋아요 여부 확인
    messages_list = []
    if device_id:
        cursor.execute('SELECT id FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        user_id = user['id'] if user else None
        
        for msg in messages:
            msg_dict = dict(msg)
            if user_id:
                cursor.execute('''
                    SELECT COUNT(*) as count FROM likes
                    WHERE user_id = ? AND message_id = ?
                ''', (user_id, msg['id']))
                is_liked = cursor.fetchone()['count'] > 0
            else:
                is_liked = False
            msg_dict['is_liked_by_user'] = is_liked
            messages_list.append(msg_dict)
    else:
        messages_list = [dict(msg) for msg in messages]
    
    conn.close()
    
    total_pages = (total + limit - 1) // limit  # 올림
    
    return {
        'messages': messages_list,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'total_pages': total_pages
        }
    }

def get_message_details(message_id, device_id=None):
    """메시지 상세 정보 조회"""
    message = get_message_by_id(message_id)
    
    if not message:
        return None
    
    # 현재 사용자의 좋아요 여부 확인
    if device_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM likes
                WHERE user_id = ? AND message_id = ?
            ''', (user['id'], message_id))
            is_liked = cursor.fetchone()['count'] > 0
            conn.close()
            message['is_liked_by_user'] = is_liked
    
    return message

def delete_message(message_id):
    """메시지 삭제 (논리적 삭제)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE messages
        SET is_deleted = 1, deleted_at = ?
        WHERE id = ?
    ''', (datetime.utcnow().isoformat(), message_id))
    
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    
    return success

# ==================== LIKE 관련 함수 ====================

def add_like(user_id, message_id):
    """좋아요 추가"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO likes (user_id, message_id, created_at)
            VALUES (?, ?, ?)
        ''', (user_id, message_id, datetime.utcnow().isoformat()))
        
        # 메시지의 likes_count 증가
        cursor.execute('''
            UPDATE messages SET likes_count = likes_count + 1
            WHERE id = ?
        ''', (message_id,))
        
        conn.commit()
        conn.close()
        return True, None
    except sqlite3.IntegrityError:
        conn.close()
        return False, "이미 좋아요한 메시지입니다."
    except Exception as e:
        conn.close()
        return False, str(e)

def remove_like(user_id, message_id):
    """좋아요 제거"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM likes
        WHERE user_id = ? AND message_id = ?
    ''', (user_id, message_id))
    
    if cursor.rowcount > 0:
        # 메시지의 likes_count 감소
        cursor.execute('''
            UPDATE messages SET likes_count = MAX(0, likes_count - 1)
            WHERE id = ?
        ''', (message_id,))
        conn.commit()
        conn.close()
        return True, None
    else:
        conn.close()
        return False, "좋아요를 찾을 수 없습니다."

def is_message_liked_by_user(user_id, message_id):
    """사용자가 메시지에 좋아요했는지 확인"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count FROM likes
        WHERE user_id = ? AND message_id = ?
    ''', (user_id, message_id))
    
    result = cursor.fetchone()
    conn.close()
    
    return result['count'] > 0

def get_message_likes_count(message_id):
    """메시지의 좋아요 수 조회"""
    message = get_message_by_id(message_id)
    return message['likes_count'] if message else 0

# ==================== 유틸리티 함수 ====================

def validate_ttl(ttl):
    """TTL 값 검증"""
    return ttl in TTL_OPTIONS

def get_pagination_params(request):
    """요청에서 페이지네이션 파라미터 추출"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        page = max(1, page)
        limit = min(max(1, limit), 50)  # 1~50 사이로 제한
        
        return page, limit
    except ValueError:
        return 1, 20

import sqlite3

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    두 위도/경도 좌표 간의 거리 계산
    """
    R = 6371000  # 지구의 반지름 (미터)
    
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(d_lat / 2) * math.sin(d_lat / 2) +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) * math.sin(d_lon / 2))
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    return distance

# ====================  동선기록,근처메세지 조회 ====================

def record_location(user_id, latitude, longitude):
    """사용자 위치 기록"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO user_locations (user_id, latitude, longitude, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, latitude, longitude, datetime.utcnow().isoformat()))
    
    conn.commit()
    conn.close()
    return True

def get_user_history(user_id, limit=50):
    """사용자 동선 히스토리 조회"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT latitude, longitude, created_at 
        FROM user_locations 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (user_id, limit))
    
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return history

def get_nearby_messages(campus_id, user_lat, user_lon, radius_m=500, device_id=None):
    """반경 내 메시지 조회"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 지워지지않은 메세지 불러오기
    cursor.execute('''
        SELECT * FROM messages 
        WHERE campus_id = ? AND is_deleted = 0
        ORDER BY created_at DESC
    ''', (campus_id,))
    messages = cursor.fetchall()
    
    # 현재 사용자의 좋아요 여부 확인용
    user_id = None
    if device_id:
        cursor.execute('SELECT id FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        if user:
            user_id = user['id']
            
    nearby_messages = []
    
    # 거리 계산하여 반경 이내인 것만 걸러냄
    for msg in messages:
        msg_dict = dict(msg)
        dist = calculate_distance(user_lat, user_lon, msg_dict['latitude'], msg_dict['longitude'])
        
        if dist <= radius_m:
            if user_id:
                cursor.execute('SELECT COUNT(*) as count FROM likes WHERE user_id = ? AND message_id = ?', (user_id, msg_dict['id']))
                msg_dict['is_liked_by_user'] = cursor.fetchone()['count'] > 0
            else:
                msg_dict['is_liked_by_user'] = False
                
            msg_dict['distance_m'] = round(dist) 
            nearby_messages.append(msg_dict)
            
    conn.close()
    return nearby_messages

def verify_location_in_campus(lat, lng, campus_id):
    """캠퍼스 반경 내에 있는지 검증"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT latitude, longitude, radius_meters FROM campuses WHERE id = ?', (campus_id,))
    campus = cursor.fetchone()
    conn.close()
    
    if not campus:
        return False, "캠퍼스를 찾을 수 없습니다."
        
    distance = calculate_distance(lat, lng, campus['latitude'], campus['longitude'])
    is_inside = distance <= campus['radius_meters']
    
    return is_inside, distance

def add_report(user_id, message_id):
    """메시지 신고 추가"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO reports (user_id, message_id, created_at)
            VALUES (?, ?, ?)
        ''', (user_id, message_id, datetime.utcnow().isoformat()))
        conn.commit()
        success, error = True, None
    except sqlite3.IntegrityError:
        #이미 신고한 유저 거르기
        success, error = False, "이미 신고한 메시지입니다."
    except Exception as e:
        success, error = False, str(e)
    finally:
        conn.close()
        
    return success, error