import qrcode
import os
from datetime import datetime, timedelta
import random
import string

def generate_order_number():
    """Generate unique order number"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f'ORD{timestamp}{random_str}'

def generate_qr_code(order_number, order_id):
    """Generate QR code for order"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    # Simple format: ORDER_NUMBER|ORDER_ID
    qr_data = f"{order_number}|{order_id}"
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists
    os.makedirs('static/qrcodes', exist_ok=True)
    
    filename = f'qr_{order_number}.png'
    filepath = os.path.join('static/qrcodes', filename)
    img.save(filepath)
    
    return filepath

def decode_qr_data(qr_string):
    """Decode QR code data
    Returns: (order_number, order_id) or None if invalid
    """
    try:
        parts = qr_string.split('|')
        if len(parts) != 2:
            return None
        
        order_number = parts[0]
        order_id = int(parts[1])
        
        return order_number, order_id
    except:
        return None

def get_available_time_slots():
    """Generate time slots starting 10 minutes from now"""
    now = datetime.now()
    start_time = now + timedelta(minutes=10)
    
    # Round to nearest 10 minutes
    start_time = start_time.replace(second=0, microsecond=0)
    minute = (start_time.minute // 10) * 10
    start_time = start_time.replace(minute=minute)
    
    slots = []
    current = start_time
    end_time = start_time + timedelta(hours=1)
    
    while current <= end_time:
        slots.append(current.strftime('%H:%M'))
        current += timedelta(minutes=10)
    
    return slots

def format_currency(amount):
    """Format amount in Indian Rupees"""
    return f'₹{amount:.2f}'