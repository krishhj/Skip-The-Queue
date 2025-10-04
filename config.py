import os
from datetime import timedelta
data_dir = os.environ.get('DATA_DIR')
if data_dir:
    db_path = os.path.join(data_dir, 'skipthequeue.db')
else:
    db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'skipthequeue.db')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///skipthequeue.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Razorpay Configuration
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID') or 'rzp_test_your_key_id'
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET') or 'your_key_secret'
    
    # Session Configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # Upload Configuration
    UPLOAD_FOLDER = 'static/qrcodes'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Email Domain Restriction
    ALLOWED_EMAIL_DOMAIN = '@somaiya.edu'