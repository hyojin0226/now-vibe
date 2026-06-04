from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import os
import uuid
from flask import send_from_directory
from werkzeug.utils import secure_filename
from config import BASE_URL, DEBUG, MESSAGE_MAX_LENGTH
from database import init_db, cleanup_expired_messages, get_db_connection
from models import (
    get_or_create_user, is_user_banned, validate_ttl,
    create_message, get_message_by_id, get_all_messages, get_message_details, delete_message,
    add_like, remove_like, is_message_liked_by_user, get_message_likes_count,
    get_pagination_params,
    record_location, get_user_history, get_nearby_messages, verify_location_in_campus, add_report 
)

# Flask 앱 초기화
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # 한글 지원
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 데이터베이스 초기화
if not os.path.exists('nowvibe.db'):
    init_db()
else:
    init_db()

# ==================== 유틸리티 함수 ====================

def success_response(data=None, status_code=200):
    """성공 응답"""
    response = {'status': 'success'}
    if data is not None:
        response['data'] = data
    return jsonify(response), status_code

def error_response(error_code, message, status_code=400):
    """에러 응답"""
    return jsonify({
        'status': 'error',
        'error_code': error_code,
        'message': message,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), status_code

def is_allowed_image(filename):
    """업로드 가능한 이미지 확장자인지 확인"""
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )

def save_uploaded_image(file_storage):
    """업로드된 이미지를 저장하고 브라우저에서 접근 가능한 URL 반환"""
    if not file_storage or not file_storage.filename:
        return None, None

    if not is_allowed_image(file_storage.filename):
        return None, '이미지는 png, jpg, jpeg, gif, webp 형식만 업로드할 수 있습니다.'

    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit('.', 1)[1].lower()
    filename = f'{uuid.uuid4().hex}.{extension}'
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))

    image_url = f'{request.host_url.rstrip("/")}/uploads/{filename}'
    return image_url, None

def get_device_id_from_request():
    """요청에서 device_id 추출"""
    # 1. JSON body에서 추출
    if request.is_json:
        device_id = request.json.get('device_id')
        if device_id:
            return device_id
    
    # 2. Query parameter에서 추출
    device_id = request.args.get('device_id')
    if device_id:
        return device_id
    
    # 3. Form data에서 추출
    device_id = request.form.get('device_id')
    if device_id:
        return device_id
    
    return None

def format_message_response(msg):
    """메시지를 응답 형식으로 변환"""
    if isinstance(msg, dict):
        return {
            'id': msg.get('id'),
            'text': msg.get('text'),
            'location': msg.get('location_name'),
            'latitude': msg.get('latitude'),
            'longitude': msg.get('longitude'),
            'likes': msg.get('likes_count', 0),
            'ttl': msg.get('ttl'),
            'image': msg.get('image_url'),
            'created_at': msg.get('created_at'),
            'expires_at': msg.get('expires_at'),
            'is_liked_by_user': msg.get('is_liked_by_user', False),
            'campus_id': msg.get('campus_id')
        }
    return msg

# ==================== 메시지 API ====================

@app.route(f'{BASE_URL}/messages', methods=['POST'])
def create_message_api():
    """메시지 생성 API"""
    try:
        # device_id 추출
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
        
        # 사용자 조회 또는 생성
        user_id = get_or_create_user(device_id)
        
        # 사용자 밴 확인
        if is_user_banned(user_id):
            return error_response('FORBIDDEN', '밴된 사용자입니다.', 403)
        
        # 필수 필드 검증
        if request.is_json:
            data = request.json
        else:
            data = request.form.to_dict()
        
        text = data.get('text', '').strip()
        if not text:
            return error_response('INVALID_INPUT', '메시지 텍스트는 필수입니다.', 400)
        
        if len(text) > MESSAGE_MAX_LENGTH:
            return error_response('INVALID_INPUT', f'메시지는 {MESSAGE_MAX_LENGTH}자 이하여야 합니다.', 400)
        
        try:
            latitude = float(data.get('latitude'))
            longitude = float(data.get('longitude'))
        except (TypeError, ValueError):
            return error_response('INVALID_INPUT', '위도/경도는 숫자여야 합니다.', 400)
        
        location_name = data.get('location_name', '')
        campus_id = data.get('campus_id')
        ttl = data.get('ttl', 3)
        image_url = data.get('image')

        if 'image' in request.files:
            image_url, upload_error = save_uploaded_image(request.files['image'])
            if upload_error:
                return error_response('INVALID_INPUT', upload_error, 400)
        
        if not campus_id:
            return error_response('INVALID_INPUT', 'campus_id가 필요합니다.', 400)
        
        try:
            campus_id = int(campus_id)
            ttl = int(ttl)
        except (TypeError, ValueError):
            return error_response('INVALID_INPUT', 'campus_id와 ttl은 정수여야 합니다.', 400)
        
        # TTL 검증
        if not validate_ttl(ttl):
            return error_response('INVALID_INPUT', f'유효한 TTL: {[3, 24, 999]}', 400)
        
        # 메시지 생성
        message = create_message(user_id, text, latitude, longitude, location_name, ttl, campus_id, image_url)
        
        if not message:
            return error_response('INTERNAL_ERROR', '메시지 생성 실패', 500)
        
        return success_response(format_message_response(message), 201)
    
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages', methods=['GET'])
def get_messages_api():
    """메시지 목록 조회 API"""
    try:
        campus_id = request.args.get('campus_id')
        if not campus_id:
            return error_response('INVALID_INPUT', 'campus_id가 필요합니다.', 400)
        
        try:
            campus_id = int(campus_id)
        except ValueError:
            return error_response('INVALID_INPUT', 'campus_id는 정수여야 합니다.', 400)
        
        sort = request.args.get('sort', 'latest')
        if sort not in ['latest', 'popular']:
            return error_response('INVALID_INPUT', 'sort는 latest 또는 popular여야 합니다.', 400)
        
        page, limit = get_pagination_params(request)
        device_id = get_device_id_from_request()
        
        # 만료된 메시지 정리
        cleanup_expired_messages()
        
        result = get_all_messages(campus_id, page, limit, sort, device_id)
        
        # 응답 형식 변환
        formatted_messages = [format_message_response(msg) for msg in result['messages']]
        result['messages'] = formatted_messages
        
        return success_response(result)
    
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages/<int:message_id>', methods=['GET'])
def get_message_api(message_id):
    """메시지 상세 조회 API"""
    try:
        device_id = get_device_id_from_request()
        message = get_message_details(message_id, device_id)
        
        if not message:
            return error_response('NOT_FOUND', '메시지를 찾을 수 없습니다.', 404)
        
        return success_response(format_message_response(message))
    
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

# ==================== 좋아요 API ====================

@app.route(f'{BASE_URL}/messages/<int:message_id>/like', methods=['POST'])
def add_like_api(message_id):
    """메시지 좋아요 추가 API"""
    try:
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
        
        # 사용자 조회
        user_id = get_or_create_user(device_id)
        
        # 메시지 존재 확인
        message = get_message_by_id(message_id)
        if not message:
            return error_response('NOT_FOUND', '메시지를 찾을 수 없습니다.', 404)
        
        # 좋아요 추가
        success, error = add_like(user_id, message_id)
        
        if not success:
            return error_response('CONFLICT', error, 409)
        
        # 업데이트된 메시지 조회
        updated_message = get_message_by_id(message_id)
        
        return success_response({
            'message_id': message_id,
            'likes_count': updated_message['likes_count'],
            'is_liked': True
        })
    
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages/<int:message_id>/like', methods=['DELETE'])
def remove_like_api(message_id):
    """메시지 좋아요 취소 API"""
    try:
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
        
        # 사용자 조회
        user_id = get_or_create_user(device_id)
        
        # 메시지 존재 확인
        message = get_message_by_id(message_id)
        if not message:
            return error_response('NOT_FOUND', '메시지를 찾을 수 없습니다.', 404)
        
        # 좋아요 제거
        success, error = remove_like(user_id, message_id)
        
        if not success:
            return error_response('NOT_FOUND', error, 404)
        
        # 업데이트된 메시지 조회
        updated_message = get_message_by_id(message_id)
        
        return success_response({
            'message_id': message_id,
            'likes_count': updated_message['likes_count'],
            'is_liked': False
        })
    
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

# ==================== 위치 및 추가 API ====================

@app.route(f'{BASE_URL}/user/location', methods=['POST'])
def record_location_api():
    """사용자 위치 기록 API"""
    try:
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
            
        user_id = get_or_create_user(device_id)
        
        if request.is_json:
            data = request.json
        else:
            data = request.form.to_dict()
            
        try:
            latitude = float(data.get('latitude'))
            longitude = float(data.get('longitude'))
        except (TypeError, ValueError):
            return error_response('INVALID_INPUT', '위도/경도는 숫자여야 합니다.', 400)
            
        record_location(user_id, latitude, longitude)
        return success_response({'message': '위치가 성공적으로 기록되었습니다.'})
        
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages/history', methods=['GET'])
def get_user_history_api():
    """사용자 동선 히스토리 조회 API"""
    try:
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
            
        user_id = get_or_create_user(device_id)
        
        limit = request.args.get('limit', 50)
        try:
            limit = int(limit)
        except ValueError:
            limit = 50
            
        history = get_user_history(user_id, limit)
        return success_response({'history': history})
        
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages/nearby', methods=['GET'])
def get_nearby_messages_api():
    """반경 기반 근처 메시지 조회 API"""
    try:
        campus_id = request.args.get('campus_id')
        if not campus_id:
            return error_response('INVALID_INPUT', 'campus_id가 필요합니다.', 400)
        try:
            campus_id = int(campus_id)
        except ValueError:
            return error_response('INVALID_INPUT', 'campus_id는 정수여야 합니다.', 400)
            
        try:
            latitude = float(request.args.get('latitude'))
            longitude = float(request.args.get('longitude'))
        except (TypeError, ValueError):
            return error_response('INVALID_INPUT', '위도/경도는 숫자여야 합니다.', 400)
            
        radius = request.args.get('radius', 500)
        try:
            radius = float(radius)
        except ValueError:
            radius = 500.0
            
        device_id = get_device_id_from_request()
        
        # 만료된 메시지 정리
        cleanup_expired_messages()
        
        messages = get_nearby_messages(campus_id, latitude, longitude, radius, device_id)
        
        # 기존 응답 형식에 맞춰 변환
        formatted_messages = []
        for msg in messages:
            formatted = format_message_response(msg)
            formatted['distance_m'] = msg.get('distance_m', 0)
            formatted_messages.append(formatted)
            
        return success_response({'messages': formatted_messages})
        
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/user/verify-campus', methods=['POST'])
def verify_campus_api():
    """캠퍼스 위치 검증 API"""
    try:
        if request.is_json:
            data = request.json
        else:
            data = request.form.to_dict()
            
        campus_id = data.get('campus_id')
        if not campus_id:
            return error_response('INVALID_INPUT', 'campus_id가 필요합니다.', 400)
        try:
            campus_id = int(campus_id)
        except ValueError:
            return error_response('INVALID_INPUT', 'campus_id는 정수여야 합니다.', 400)
            
        try:
            latitude = float(data.get('latitude'))
            longitude = float(data.get('longitude'))
        except (TypeError, ValueError):
            return error_response('INVALID_INPUT', '위도/경도는 숫자여야 합니다.', 400)
            
        is_inside, distance = verify_location_in_campus(latitude, longitude, campus_id)
        
        return success_response({
            'is_inside': is_inside,
            'distance_meters': round(distance)
        })
        
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

@app.route(f'{BASE_URL}/messages/<int:message_id>/report', methods=['POST'])
def report_message_api(message_id):
    """메시지 신고 API"""
    try:
        device_id = get_device_id_from_request()
        if not device_id:
            return error_response('INVALID_INPUT', 'device_id가 필요합니다.', 400)
            
        user_id = get_or_create_user(device_id)
        
        # 메시지가 존재하는지 먼저 확인
        message = get_message_by_id(message_id)
        if not message:
            return error_response('NOT_FOUND', '메시지를 찾을 수 없습니다.', 404)
            
        success, error = add_report(user_id, message_id)
        if not success:
            return error_response('CONFLICT', error, 409)
            
        return success_response({
            'message_id': message_id,
            'status': 'reported',
            'message': '신고가 정상적으로 접수되었습니다.'
        })
        
    except Exception as e:
        return error_response('INTERNAL_ERROR', str(e), 500)

# ==================== Health Check ====================

@app.route(f'{BASE_URL}/health', methods=['GET'])
def health_check():
    """서버 상태 확인"""
    return success_response({'status': 'healthy'})

@app.route('/uploads/<path:filename>', methods=['GET'])
def uploaded_file(filename):
    """업로드된 이미지 파일 제공"""
    return send_from_directory(UPLOAD_FOLDER, filename)

# ==================== 에러 핸들러 ====================

@app.errorhandler(404)
def not_found(error):
    return error_response('NOT_FOUND', '요청한 리소스를 찾을 수 없습니다.', 404)

@app.errorhandler(500)
def internal_error(error):
    return error_response('INTERNAL_ERROR', '서버 내부 오류가 발생했습니다.', 500)

# ==================== 메인 ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 Now Vibe API Server - Developer A (메시지 코어 기능)")
    print("="*60)
    print(f"📍 Server: http://localhost:5001")
    print(f"📚 API Base: http://localhost:5001{BASE_URL}")
    print(f"💾 Database: nowvibe.db")
    print("="*60)
    print("\n✅ 지원 API:")
    print("  1. POST   /api/messages              - 메시지 생성")
    print("  2. GET    /api/messages              - 메시지 목록 조회")
    print("  3. GET    /api/messages/<id>        - 메시지 상세 조회")
    print("  4. POST   /api/messages/<id>/like   - 좋아요 추가")
    print("  5. DELETE /api/messages/<id>/like   - 좋아요 취소")
    print("  6. GET    /api/health                - 상태 확인")
    print("="*60 + "\n")
    
    app.run(debug=DEBUG, host='0.0.0.0', port=5001)
