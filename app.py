import os
import time
import hashlib
import hmac
import base64
import requests
import redis
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from datetime import datetime
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Setup logging
logging.basicConfig(
    filename=app.config['LOG_FILE'],
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MyXL-OTP-Service')

# Inisialisasi Redis
redis_client = redis.Redis(
    host=app.config['REDIS_HOST'],
    port=app.config['REDIS_PORT'],
    password=app.config['REDIS_PASSWORD'],
    db=app.config['REDIS_DB']
)

# Setup rate limiter
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=[app.config['RATE_LIMIT']]
)

def generate_ftth_signature(secret, message):
    """Generate HMAC signature untuk FTTH API"""
    return hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def call_ftth_api(endpoint, payload={}, method='POST'):
    """Panggil MyXL FTTH API dengan autentikasi yang benar"""
    timestamp = str(int(time.time()))
    signature_data = f"{timestamp}{app.config['API_KEY']}{endpoint}"
    signature = generate_ftth_signature(app.config['API_SECRET'], signature_data)
    
    headers = {
        'FTTH-Api-Package': app.config['API_PACKAGE'],
        'Key': app.config['API_KEY'],
        'Timestamp': timestamp,
        'Signature': signature,
        'Content-Type': 'application/json'
    }
    
    url = f"{app.config['BASE_URL']}{endpoint}"
    
    try:
        if method == 'POST':
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        else:
            response = requests.get(url, headers=headers, params=payload, timeout=10)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"FTTH API error: {str(e)}")
        return None

def normalize_phone_number(phone):
    """Normalisasi nomor telepon ke format MyXL"""
    cleaned = ''.join(filter(str.isdigit, phone))
    
    if cleaned.startswith('0'):
        return '62' + cleaned[1:]
    elif cleaned.startswith('62'):
        return cleaned
    elif cleaned.startswith('+62'):
        return cleaned[1:]
    else:
        return '62' + cleaned

def generate_otp(phone):
    """Generate OTP 6 digit dengan salt berbasis waktu"""
    timestamp = int(time.time())
    salt = f"{phone}{app.config['SECRET_KEY']}{timestamp}"
    hasher = hashlib.sha256(salt.encode())
    otp = str(int(hasher.hexdigest()[:6], 16))[-6:].zfill(6)
    return otp

def send_sms_via_ftth_api(phone, otp):
    """Kirim SMS menggunakan FTTH API"""
    message = f"Kode OTP MyXL Anda: {otp}. Berlaku 5 menit. JANGAN BERIKAN kode ini kepada siapapun."
    
    payload = {
        "msisdn": phone,
        "message": message,
        "sms_type": "transactional",
        "sender_id": "MYXL"
    }
    
    response = call_ftth_api("sms/send", payload)
    
    if response and response.get('status') == 'success':
        logger.info(f"SMS sent to {phone} via FTTH API")
        return True
    else:
        logger.error(f"Failed to send SMS to {phone}: {response}")
        return False

def validate_customer_ftth(phone):
    """Validasi pelanggan melalui FTTH API"""
    payload = {"msisdn": phone}
    response = call_ftth_api("customer/validate", payload, 'GET')
    
    if response and response.get('status') == 'success':
        return True, response.get('data', {})
    return False, {}

def get_otp_metrics():
    """Ambil metrik penggunaan OTP dari Redis"""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "total": int(redis_client.get(f"otp:stats:{today}:total") or 0),
        "success": int(redis_client.get(f"otp:stats:{today}:success") or 0),
        "failed": int(redis_client.get(f"otp:stats:{today}:failed") or 0)
    }

def update_otp_metrics(success=True):
    """Update statistik penggunaan OTP"""
    today = datetime.now().strftime("%Y-%m-%d")
    redis_client.incr(f"otp:stats:{today}:total")
    if success:
        redis_client.incr(f"otp:stats:{today}:success")
    else:
        redis_client.incr(f"otp:stats:{today}:failed")

@app.route('/api/otp/request', methods=['POST'])
@limiter.limit("3 per minute")
def request_otp():
    """Endpoint untuk meminta OTP"""
    data = request.get_json()
    phone = data.get('phone')
    
    if not phone:
        return jsonify({
            "status": "error",
            "code": "INVALID_PHONE",
            "message": "Nomor telepon diperlukan"
        }), 400
    
    normalized_phone = normalize_phone_number(phone)
    if not normalized_phone.startswith('628'):
        return jsonify({
            "status": "error",
            "code": "INVALID_PHONE_FORMAT",
            "message": "Format nomor harus 08xx atau 628xx (Indonesia)"
        }), 400
    
    rate_key = f"otp_rate:{normalized_phone}"
    if redis_client.get(rate_key):
        return jsonify({
            "status": "error",
            "code": "RATE_LIMITED",
            "message": "Terlalu banyak permintaan. Silakan coba lagi nanti."
        }), 429
    
    is_valid, customer_data = validate_customer_ftth(normalized_phone)
    if not is_valid:
        return jsonify({
            "status": "error",
            "code": "INVALID_CUSTOMER",
            "message": "Nomor tidak terdaftar sebagai pelanggan MyXL FTTH"
        }), 400
    
    otp = generate_otp(normalized_phone)
    otp_key = f"otp:{normalized_phone}"
    redis_client.setex(otp_key, app.config['OTP_EXPIRY'], otp)
    redis_client.setex(rate_key, 60, "1")
    
    sms_sent = send_sms_via_ftth_api(normalized_phone, otp)
    update_otp_metrics(success=sms_sent)
    
    if sms_sent:
        return jsonify({
            "status": "success",
            "message": "OTP telah dikirim",
            "data": {
                "phone": normalized_phone,
                "expires_in": app.config['OTP_EXPIRY'],
                "customer": {
                    "name": customer_data.get('name', ''),
                    "package": customer_data.get('package', '')
                }
            }
        })
    else:
        return jsonify({
            "status": "error",
            "code": "SMS_FAILED",
            "message": "Gagal mengirim SMS. Silakan coba lagi."
        }), 500

@app.route('/api/otp/verify', methods=['POST'])
def verify_otp():
    """Endpoint untuk verifikasi OTP"""
    data = request.get_json()
    phone = data.get('phone')
    otp_attempt = data.get('otp')
    
    if not phone or not otp_attempt:
        return jsonify({
            "status": "error",
            "code": "MISSING_PARAMETERS",
            "message": "Nomor telepon dan OTP diperlukan"
        }), 400
    
    normalized_phone = normalize_phone_number(phone)
    otp_key = f"otp:{normalized_phone}"
    stored_otp = redis_client.get(otp_key)
    
    if not stored_otp:
        return jsonify({
            "status": "error",
            "code": "OTP_EXPIRED",
            "message": "OTP tidak valid atau sudah kadaluarsa"
        }), 401
    
    if stored_otp.decode() == otp_attempt:
        redis_client.delete(otp_key)
        log_payload = {
            "msisdn": normalized_phone,
            "activity": "otp_verification",
            "status": "success"
        }
        call_ftth_api("activity/log", log_payload)
        return jsonify({
            "status": "success",
            "message": "OTP valid"
        })
    else:
        return jsonify({
            "status": "error",
            "code": "INVALID_OTP",
            "message": "OTP tidak valid"
        }), 401

@app.route('/api/otp/metrics', methods=['GET'])
def get_metrics():
    """Endpoint untuk mendapatkan metrik penggunaan OTP"""
    metrics = get_otp_metrics()
    return jsonify({
        "status": "success",
        "data": metrics
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "success",
        "message": "OTP Service is running",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG']
    )
