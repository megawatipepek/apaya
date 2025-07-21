import os

class Config:
    # Konfigurasi Aplikasi
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5000))
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    SECRET_KEY = os.getenv('SECRET_KEY', 'myxl-secret-key-axiata')
    
    # Konfigurasi Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    
    # Konfigurasi FTTH API
    BASE_URL = os.getenv('BASE_URL', 'https://api.myxl.xlaxiata.co.id/ftth/api/v8/')
    API_KEY = os.getenv('API_KEY', 'nskuuxz5xhz5fcyv5fpayt8r')
    API_SECRET = os.getenv('API_SECRET', 'xAf4bDJUxE')
    API_PACKAGE = os.getenv('API_PACKAGE', 'Default-Plan')
    
    # Konfigurasi Layanan
    OTP_EXPIRY = int(os.getenv('OTP_EXPIRY', 300))  # 5 menit
    RATE_LIMIT = os.getenv('RATE_LIMIT', '5 per minute')
    LOG_FILE = os.getenv('LOG_FILE', '/var/log/myxl-otp-service.log')
