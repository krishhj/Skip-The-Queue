from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room
from config import Config
from models import db, User, Category, MenuItem, Order, OrderItem
from forms import SignupForm, LoginForm, MenuItemForm
from utils import generate_order_number, generate_qr_code, get_available_time_slots
import razorpay
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func, and_
import json

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET']))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Role-based access control decorator
def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != role:
                flash('Access denied. You do not have permission to view this page.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Authentication Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'student':
            return redirect(url_for('student_home'))
        elif current_user.role == 'vendor':
            return redirect(url_for('vendor_dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = SignupForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data,
            full_name=form.full_name.data,
            phone=form.phone.data,
            role='student'  # Default role
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            if user.role == 'student':
                return redirect(url_for('student_home'))
            elif user.role == 'vendor':
                return redirect(url_for('vendor_dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

# Student Routes
@app.route('/student/home')
@login_required
@role_required('student')
def student_home():
    categories = Category.query.all()
    
    # Calculate sustainability impact for student
    student_orders = Order.query.filter_by(student_id=current_user.id).count()
    waste_saved = student_orders * 0.25  # Estimate 250g per order
    
    return render_template('student/home.html', 
                         categories=categories,
                         student_orders=student_orders,
                         waste_saved=waste_saved)

@app.route('/student/category/<int:category_id>')
@login_required
@role_required('student')
def category_menu(category_id):
    category = Category.query.get_or_404(category_id)
    menu_items = MenuItem.query.filter_by(category_id=category_id, is_available=True).all()
    return render_template('student/category.html', category=category, menu_items=menu_items)

@app.route('/student/add-to-cart', methods=['POST'])
@login_required
@role_required('student')
def add_to_cart():
    data = request.get_json()
    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    
    menu_item = MenuItem.query.get_or_404(item_id)
    
    # Initialize cart in session
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    item_key = str(item_id)
    
    if item_key in cart:
        cart[item_key]['quantity'] += quantity
    else:
        cart[item_key] = {
            'id': item_id,
            'name': menu_item.name,
            'price': menu_item.price,
            'quantity': quantity,
            'vendor_id': menu_item.vendor_id
        }
    
    session['cart'] = cart
    session.modified = True
    
    return jsonify({'success': True, 'cart_count': len(cart)})

@app.route('/student/cart')
@login_required
@role_required('student')
def view_cart():
    cart = session.get('cart', {})
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    time_slots = get_available_time_slots()
    
    # Get vendor slot config if cart has items
    slot_availability = {}
    if cart:
        vendor_id = list(cart.values())[0]['vendor_id']
        vendor = User.query.get(vendor_id)
        if vendor:
            slot_config = vendor.get_slot_config()
            for slot in time_slots:
                if slot in slot_config:
                    config = slot_config[slot]
                    if config.get('blackout', False):
                        slot_availability[slot] = {'available': False, 'reason': 'Unavailable'}
                    else:
                        capacity = config.get('capacity', 20)
                        booked = Order.query.filter_by(
                            vendor_id=vendor_id,
                            pickup_time=slot
                        ).filter(Order.created_at >= datetime.now().date()).count()
                        slot_availability[slot] = {
                            'available': booked < capacity,
                            'capacity': capacity,
                            'booked': booked,
                            'percentage': int((booked / capacity) * 100) if capacity > 0 else 0
                        }
                else:
                    slot_availability[slot] = {'available': True, 'capacity': 20, 'booked': 0, 'percentage': 0}
    
    return render_template('student/cart.html', cart=cart, total=total, 
                         time_slots=time_slots, slot_availability=slot_availability)

@app.route('/student/update-cart', methods=['POST'])
@login_required
@role_required('student')
def update_cart():
    data = request.get_json()
    item_id = str(data.get('item_id'))
    action = data.get('action')
    
    cart = session.get('cart', {})
    
    if item_id in cart:
        if action == 'increase':
            cart[item_id]['quantity'] += 1
        elif action == 'decrease':
            cart[item_id]['quantity'] -= 1
            if cart[item_id]['quantity'] <= 0:
                del cart[item_id]
        elif action == 'remove':
            del cart[item_id]
    
    session['cart'] = cart
    session.modified = True
    
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    return jsonify({'success': True, 'total': total, 'cart_count': len(cart)})

@app.route('/student/checkout', methods=['POST'])
@login_required
@role_required('student')
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('student_home'))
    
    pickup_time = request.form.get('pickup_time')
    special_instructions = request.form.get('special_instructions', '')
    payment_method = request.form.get('payment_method')
    
    if not pickup_time:
        flash('Please select a pickup time', 'warning')
        return redirect(url_for('view_cart'))
    
    total_amount = sum(item['price'] * item['quantity'] for item in cart.values())
    
    # Get vendor_id from cart items (assuming all items from same vendor for MVP)
    vendor_id = list(cart.values())[0]['vendor_id']
    
    # Check slot availability
    vendor = User.query.get(vendor_id)
    slot_config = vendor.get_slot_config() if vendor else {}
    if pickup_time in slot_config:
        config = slot_config[pickup_time]
        if config.get('blackout', False):
            flash('Selected time slot is not available', 'warning')
            return redirect(url_for('view_cart'))
        
        capacity = config.get('capacity', 20)
        booked = Order.query.filter_by(vendor_id=vendor_id, pickup_time=pickup_time).filter(
            Order.created_at >= datetime.now().date()).count()
        
        if booked >= capacity:
            flash('Selected time slot is full. Please choose another time.', 'warning')
            return redirect(url_for('view_cart'))
    
    # Create order
    order_number = generate_order_number()
    order = Order(
        order_number=order_number,
        student_id=current_user.id,
        vendor_id=vendor_id,
        total_amount=total_amount,
        payment_method=payment_method,
        pickup_time=pickup_time,
        special_instructions=special_instructions,
        payment_status='pending' if payment_method == 'online' else 'cod',
        order_status='placed'
    )
    
    db.session.add(order)
    db.session.flush()  # Get order ID
    
    # Add order items
    for item in cart.values():
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item['id'],
            quantity=item['quantity'],
            price=item['price']
        )
        db.session.add(order_item)
    
    if payment_method == 'online':
        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(total_amount * 100),  # Amount in paise
            'currency': 'INR',
            'payment_capture': 1
        })
        order.razorpay_order_id = razorpay_order['id']
        db.session.commit()
        
        return render_template('student/checkout.html', 
                             order=order, 
                             razorpay_key=app.config['RAZORPAY_KEY_ID'],
                             razorpay_order_id=razorpay_order['id'])
    else:
        # COD - Generate QR code immediately
        qr_path = generate_qr_code(order_number, order.id)
        order.qr_code_path = qr_path
        order.payment_status = 'cod'
        db.session.commit()
        
        # Clear cart
        session['cart'] = {}
        session.modified = True
        
        # Notify vendor via SocketIO
        socketio.emit('new_order', {
            'order_id': order.id,
            'order_number': order_number,
            'total_amount': total_amount,
            'pickup_time': pickup_time
        }, room=f'vendor_{vendor_id}')
        
        # Check slot capacity warning
        check_slot_capacity_warning(vendor_id, pickup_time)
        
        return redirect(url_for('order_success', order_id=order.id))

@app.route('/student/payment-success', methods=['POST'])
@login_required
@role_required('student')
def payment_success():
    data = request.get_json()
    order_id = data.get('order_id')
    payment_id = data.get('payment_id')
    
    order = Order.query.get_or_404(order_id)
    order.razorpay_payment_id = payment_id
    order.payment_status = 'paid'
    
    # Generate QR code
    qr_path = generate_qr_code(order.order_number, order.id)
    order.qr_code_path = qr_path
    
    db.session.commit()
    
    # Clear cart
    session['cart'] = {}
    session.modified = True
    
    # Notify vendor
    socketio.emit('new_order', {
        'order_id': order.id,
        'order_number': order.order_number,
        'total_amount': order.total_amount,
        'pickup_time': order.pickup_time
    }, room=f'vendor_{order.vendor_id}')
    
    # Check slot capacity warning
    check_slot_capacity_warning(order.vendor_id, order.pickup_time)
    
    return jsonify({'success': True, 'redirect_url': url_for('order_success', order_id=order.id)})

@app.route('/student/order-success/<int:order_id>')
@login_required
@role_required('student')
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    if order.student_id != current_user.id:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('student_home'))
    return render_template('student/order_success.html', order=order)

@app.route('/student/my-orders')
@login_required
@role_required('student')
def my_orders():
    orders = Order.query.filter_by(student_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('student/my_orders.html', orders=orders)

# Vendor Routes
@app.route('/vendor/dashboard')
@login_required
@role_required('vendor')
def vendor_dashboard():
    today = datetime.now().date()
    
    # Basic stats
    pending_orders = Order.query.filter_by(vendor_id=current_user.id, order_status='placed').count()
    today_orders = Order.query.filter_by(vendor_id=current_user.id).filter(
        func.date(Order.created_at) == today).count()
    total_orders = Order.query.filter_by(vendor_id=current_user.id).count()
    menu_items = MenuItem.query.filter_by(vendor_id=current_user.id).count()
    
    # Today's revenue
    today_revenue = db.session.query(func.sum(Order.total_amount)).filter(
        Order.vendor_id == current_user.id,
        func.date(Order.created_at) == today,
        Order.payment_status.in_(['paid', 'cod'])
    ).scalar() or 0
    
    # Low stock items
    low_stock_items = get_low_stock_items(current_user.id)
    
    # Peak hours for today
    peak_hours = get_peak_hours_today(current_user.id)
    
    # Slot utilization
    slot_stats = get_slot_utilization(current_user.id)
    
    # Sustainability metrics
    waste_prevented = calculate_waste_prevented(current_user.id)
    
    return render_template('vendor/dashboard.html', 
                         pending_orders=pending_orders,
                         today_orders=today_orders,
                         total_orders=total_orders,
                         menu_items=menu_items,
                         today_revenue=today_revenue,
                         low_stock_items=low_stock_items,
                         peak_hours=peak_hours,
                         slot_stats=slot_stats,
                         waste_prevented=waste_prevented)

@app.route('/vendor/orders')
@login_required
@role_required('vendor')
def vendor_orders():
    status_filter = request.args.get('status', 'all')
    query = Order.query.filter_by(vendor_id=current_user.id)
    
    if status_filter != 'all':
        query = query.filter_by(order_status=status_filter)
    
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('vendor/orders.html', orders=orders, status_filter=status_filter)

@app.route('/vendor/update-order-status', methods=['POST'])
@login_required
@role_required('vendor')
def update_order_status():
    data = request.get_json()
    order_id = data.get('order_id')
    new_status = data.get('status')
    
    order = Order.query.get_or_404(order_id)
    
    if order.vendor_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    order.order_status = new_status
    
    if new_status == 'picked_up':
        order.picked_up_at = datetime.utcnow()
    
    db.session.commit()
    
    # Notify student via SocketIO
    socketio.emit('order_status_update', {
        'order_id': order.id,
        'status': new_status,
        'message': get_status_message(new_status)
    }, room=f'student_{order.student_id}')
    
    return jsonify({'success': True})

@app.route('/vendor/verify-order-manual', methods=['POST'])
@login_required
@role_required('vendor')
def verify_order_manual():
    """Manual order verification by order number"""
    data = request.get_json()
    order_number = data.get('order_number', '').strip().upper()
    
    if not order_number:
        return jsonify({'success': False, 'message': 'Please enter an order number'}), 400
    
    try:
        # Find order by order number
        order = Order.query.filter_by(order_number=order_number).first()
        
        if not order:
            return jsonify({'success': False, 'message': 'Order not found. Please check the order number.'}), 404
        
        if order.vendor_id != current_user.id:
            return jsonify({'success': False, 'message': 'This order is not for your outlet'}), 403
        
        if order.order_status == 'picked_up':
            return jsonify({'success': False, 'message': 'This order has already been picked up'}), 400
        
        # Update order status
        order.order_status = 'picked_up'
        order.picked_up_at = datetime.utcnow()
        db.session.commit()
        
        # Notify student
        socketio.emit('order_status_update', {
            'order_id': order.id,
            'status': 'picked_up',
            'message': 'Order picked up successfully!'
        }, room=f'student_{order.student_id}')
        
        return jsonify({
            'success': True,
            'message': 'Pickup confirmed!',
            'order': {
                'order_number': order.order_number,
                'customer_name': order.customer.full_name,
                'total_amount': order.total_amount
            }
        })
        
    except Exception as e:
        print(f"Manual Verify Error: {str(e)}")
        return jsonify({'success': False, 'message': 'Error processing order verification'}), 500

@app.route('/vendor/scan-qr', methods=['POST'])
@login_required
@role_required('vendor')
def scan_qr():
    data = request.get_json()
    qr_data = data.get('qr_data')
    
    try:
        from utils import decode_qr_data
        
        # Decode QR data
        result = decode_qr_data(qr_data)
        if not result:
            return jsonify({'success': False, 'message': 'Invalid QR code format'}), 400
        
        order_number, order_id = result
        
        # Get order from database
        order = Order.query.get(order_id)
        
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 400
        
        if order.order_number != order_number:
            return jsonify({'success': False, 'message': 'Invalid QR code'}), 400
        
        if order.vendor_id != current_user.id:
            return jsonify({'success': False, 'message': 'This order is not for your outlet'}), 403
        
        if order.order_status == 'picked_up':
            return jsonify({'success': False, 'message': 'Order already picked up'}), 400
        
        # Update order status
        order.order_status = 'picked_up'
        order.picked_up_at = datetime.utcnow()
        db.session.commit()
        
        # Notify student
        socketio.emit('order_status_update', {
            'order_id': order.id,
            'status': 'picked_up',
            'message': 'Order picked up successfully!'
        }, room=f'student_{order.student_id}')
        
        return jsonify({
            'success': True, 
            'message': 'Pickup confirmed!',
            'order': {
                'order_number': order.order_number,
                'customer_name': order.customer.full_name,
                'total_amount': order.total_amount
            }
        })
        
    except Exception as e:
        print(f"QR Scan Error: {str(e)}")
        return jsonify({'success': False, 'message': f'Error processing QR code: {str(e)}'}), 400

@app.route('/vendor/qr-scanner')
@login_required
@role_required('vendor')
def qr_scanner():
    return render_template('vendor/qr_scanner.html')

@app.route('/vendor/menu')
@login_required
@role_required('vendor')
def vendor_menu():
    menu_items = MenuItem.query.filter_by(vendor_id=current_user.id).all()
    return render_template('vendor/menu_management.html', menu_items=menu_items)

@app.route('/vendor/menu/add', methods=['GET', 'POST'])
@login_required
@role_required('vendor')
def add_menu_item():
    form = MenuItemForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        menu_item = MenuItem(
            name=form.name.data,
            description=form.description.data,
            price=form.price.data,
            category_id=form.category_id.data,
            vendor_id=current_user.id,
            is_available=form.is_available.data
        )
        db.session.add(menu_item)
        db.session.commit()
        flash('Menu item added successfully', 'success')
        return redirect(url_for('vendor_menu'))
    
    return render_template('vendor/menu_management.html', form=form, menu_items=[])

@app.route('/vendor/menu/toggle/<int:item_id>', methods=['POST'])
@login_required
@role_required('vendor')
def toggle_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    
    if item.vendor_id != current_user.id:
        return jsonify({'success': False}), 403
    
    item.is_available = not item.is_available
    db.session.commit()
    
    return jsonify({'success': True, 'is_available': item.is_available})

@app.route('/vendor/analytics')
@login_required
@role_required('vendor')
def vendor_analytics():
    # Get data for analytics
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    
    # Orders and revenue
    orders = Order.query.filter_by(vendor_id=current_user.id).all()
    total_revenue = sum(o.total_amount for o in orders if o.payment_status in ['paid', 'cod'])
    
    # Peak hours data
    peak_hours_data = get_peak_hours_weekly(current_user.id)
    
    # Slot utilization
    slot_utilization_data = get_detailed_slot_utilization(current_user.id)
    
    # Waste reduction metrics
    waste_metrics = get_detailed_waste_metrics(current_user.id)
    
    # Popular items
    popular_items = get_popular_items(current_user.id)
    
    return render_template('vendor/analytics.html', 
                         orders=orders,
                         total_revenue=total_revenue,
                         peak_hours_data=peak_hours_data,
                         slot_utilization_data=slot_utilization_data,
                         waste_metrics=waste_metrics,
                         popular_items=popular_items)

@app.route('/vendor/slot-management')
@login_required
@role_required('vendor')
def slot_management():
    slot_config = current_user.get_slot_config()
    time_slots = get_available_time_slots()
    
    return render_template('vendor/slot_management.html', 
                         slot_config=slot_config,
                         time_slots=time_slots)

@app.route('/vendor/update-slot-config', methods=['POST'])
@login_required
@role_required('vendor')
def update_slot_config():
    data = request.get_json()
    slot_time = data.get('slot_time')
    capacity = data.get('capacity')
    blackout = data.get('blackout', False)
    
    slot_config = current_user.get_slot_config()
    
    if slot_time not in slot_config:
        slot_config[slot_time] = {}
    
    if capacity is not None:
        slot_config[slot_time]['capacity'] = int(capacity)
    
    if blackout is not None:
        slot_config[slot_time]['blackout'] = blackout
    
    current_user.set_slot_config(slot_config)
    db.session.commit()
    
    # Notify about slot changes
    socketio.emit('slot_config_updated', {
        'slot_time': slot_time,
        'capacity': capacity,
        'blackout': blackout
    }, room=f'vendor_{current_user.id}')
    
    return jsonify({'success': True})

# Helper functions
def get_low_stock_items(vendor_id):
    """Get items with low stock based on recent orders"""
    items_with_orders = db.session.query(
        MenuItem.id,
        MenuItem.name,
        MenuItem.stock_threshold,
        func.sum(OrderItem.quantity).label('total_ordered')
    ).join(OrderItem).join(Order).filter(
        MenuItem.vendor_id == vendor_id,
        Order.created_at >= datetime.now().date()
    ).group_by(MenuItem.id).all()
    
    low_stock = []
    for item in items_with_orders:
        if item.total_ordered >= item.stock_threshold:
            low_stock.append({
                'name': item.name,
                'ordered': item.total_ordered,
                'threshold': item.stock_threshold
            })
    
    return low_stock

def get_peak_hours_today(vendor_id):
    """Get order count by hour for today"""
    today = datetime.now().date()
    
    orders = db.session.query(
        func.strftime('%H', Order.created_at).label('hour'),
        func.count(Order.id).label('count')
    ).filter(
        Order.vendor_id == vendor_id,
        func.date(Order.created_at) == today
    ).group_by('hour').all()
    
    hours_data = {str(i).zfill(2): 0 for i in range(24)}
    for order in orders:
        hours_data[order.hour] = order.count
    
    return hours_data

def get_peak_hours_weekly(vendor_id):
    """Get order count by hour for past week"""
    week_ago = datetime.now() - timedelta(days=7)
    
    orders = db.session.query(
        func.strftime('%H', Order.created_at).label('hour'),
        func.count(Order.id).label('count')
    ).filter(
        Order.vendor_id == vendor_id,
        Order.created_at >= week_ago
    ).group_by('hour').all()
    
    return [{'hour': o.hour, 'count': o.count} for o in orders]

def get_slot_utilization(vendor_id):
    """Get today's slot booking statistics"""
    today = datetime.now().date()
    
    slot_config = User.query.get(vendor_id).get_slot_config()
    time_slots = get_available_time_slots()
    
    total_slots = 0
    booked_slots = 0
    
    for slot in time_slots:
        capacity = 20  # Default
        if slot in slot_config:
            if slot_config[slot].get('blackout', False):
                continue
            capacity = slot_config[slot].get('capacity', 20)
        
        booked = Order.query.filter_by(
            vendor_id=vendor_id,
            pickup_time=slot
        ).filter(func.date(Order.created_at) == today).count()
        
        total_slots += capacity
        booked_slots += booked
    
    utilization = (booked_slots / total_slots * 100) if total_slots > 0 else 0
    
    return {
        'total': total_slots,
        'booked': booked_slots,
        'utilization': round(utilization, 1)
    }

def get_detailed_slot_utilization(vendor_id):
    """Get detailed slot utilization for analytics"""
    today = datetime.now().date()
    slot_config = User.query.get(vendor_id).get_slot_config()
    time_slots = get_available_time_slots()
    
    slots_data = []
    for slot in time_slots:
        capacity = 20
        if slot in slot_config:
            if slot_config[slot].get('blackout', False):
                continue
            capacity = slot_config[slot].get('capacity', 20)
        
        booked = Order.query.filter_by(
            vendor_id=vendor_id,
            pickup_time=slot
        ).filter(func.date(Order.created_at) == today).count()
        
        utilization = (booked / capacity * 100) if capacity > 0 else 0
        
        slots_data.append({
            'time': slot,
            'capacity': capacity,
            'booked': booked,
            'utilization': round(utilization, 1)
        })
    
    return slots_data

def calculate_waste_prevented(vendor_id):
    """Calculate waste prevented through pre-ordering"""
    total_orders = Order.query.filter_by(vendor_id=vendor_id).count()
    
    # Estimate: Each pre-order prevents 250g of waste
    kg_saved = total_orders * 0.25
    
    today_orders = Order.query.filter_by(vendor_id=vendor_id).filter(
        func.date(Order.created_at) == datetime.now().date()
    ).count()
    
    today_kg_saved = today_orders * 0.25
    
    return {
        'total_orders': total_orders,
        'total_kg_saved': round(kg_saved, 2),
        'today_orders': today_orders,
        'today_kg_saved': round(today_kg_saved, 2)
    }

def get_detailed_waste_metrics(vendor_id):
    """Get detailed waste prevention metrics"""
    week_ago = datetime.now() - timedelta(days=7)
    
    weekly_orders = Order.query.filter_by(vendor_id=vendor_id).filter(
        Order.created_at >= week_ago
    ).count()
    
    weekly_kg_saved = weekly_orders * 0.25
    
    return {
        'weekly_orders': weekly_orders,
        'weekly_kg_saved': round(weekly_kg_saved, 2),
        'message': 'Smart scheduling helps canteens prepare exact quantities, reducing stale food and leftovers'
    }

def get_popular_items(vendor_id):
    """Get most popular menu items"""
    popular = db.session.query(
        MenuItem.name,
        func.sum(OrderItem.quantity).label('total_sold')
    ).join(OrderItem).join(Order).filter(
        MenuItem.vendor_id == vendor_id
    ).group_by(MenuItem.id).order_by(func.sum(OrderItem.quantity).desc()).limit(10).all()
    
    return [{'name': p.name, 'total_sold': p.total_sold} for p in popular]

def check_slot_capacity_warning(vendor_id, slot_time):
    """Check if slot is reaching capacity and send warning"""
    slot_config = User.query.get(vendor_id).get_slot_config()
    capacity = 20
    
    if slot_time in slot_config:
        capacity = slot_config[slot_time].get('capacity', 20)
    
    booked = Order.query.filter_by(
        vendor_id=vendor_id,
        pickup_time=slot_time
    ).filter(func.date(Order.created_at) == datetime.now().date()).count()
    
    utilization = (booked / capacity) * 100 if capacity > 0 else 0
    
    if utilization >= 90:
        socketio.emit('slot_capacity_warning', {
            'slot_time': slot_time,
            'utilization': round(utilization, 1),
            'message': f'Slot {slot_time} is {round(utilization, 1)}% full!'
        }, room=f'vendor_{vendor_id}')

def get_status_message(status):
    """Get friendly status message"""
    messages = {
        'placed': 'Order placed successfully!',
        'confirmed': 'Order confirmed by vendor',
        'preparing': 'Your order is being prepared',
        'ready': 'Your order is ready for pickup!',
        'picked_up': 'Order picked up successfully',
        'cancelled': 'Order cancelled'
    }
    return messages.get(status, 'Order status updated')

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        room = f'{current_user.role}_{current_user.id}'
        join_room(room)
        print(f'User {current_user.id} joined room {room}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'User disconnected')

# Initialize database and create default data
def init_db():
    with app.app_context():
        db.create_all()
        
        # Create default categories if they don't exist
        if Category.query.count() == 0:
            categories = [
                Category(name='Chai & Coffee', description='Hot beverages and tea', icon='bi-cup-hot'),
                Category(name='Snacks & Quick Bites', description='Vadapav, Samosa, and more', icon='bi-egg-fried'),
                Category(name='Main Course', description='Full meals and thalis', icon='bi-bowl-hot'),
                Category(name='Drinks & Beverages', description='Cold drinks and juices', icon='bi-cup-straw')
            ]
            for category in categories:
                db.session.add(category)
            db.session.commit()
            print('Categories created successfully')

if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, port=5000)
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room
from config import Config
from models import db, User, Category, MenuItem, Order, OrderItem
from forms import SignupForm, LoginForm, MenuItemForm
from utils import generate_order_number, generate_qr_code, get_available_time_slots
import razorpay
from functools import wraps

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET']))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Role-based access control decorator
def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != role:
                flash('Access denied. You do not have permission to view this page.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Authentication Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'student':
            return redirect(url_for('student_home'))
        elif current_user.role == 'vendor':
            return redirect(url_for('vendor_dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = SignupForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data,
            full_name=form.full_name.data,
            phone=form.phone.data,
            role='student'  # Default role
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            if user.role == 'student':
                return redirect(url_for('student_home'))
            elif user.role == 'vendor':
                return redirect(url_for('vendor_dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

# Student Routes
@app.route('/student/home')
@login_required
@role_required('student')
def student_home():
    categories = Category.query.all()
    return render_template('student/home.html', categories=categories)

@app.route('/student/category/<int:category_id>')
@login_required
@role_required('student')
def category_menu(category_id):
    category = Category.query.get_or_404(category_id)
    menu_items = MenuItem.query.filter_by(category_id=category_id, is_available=True).all()
    return render_template('student/category.html', category=category, menu_items=menu_items)

@app.route('/student/add-to-cart', methods=['POST'])
@login_required
@role_required('student')
def add_to_cart():
    data = request.get_json()
    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    
    menu_item = MenuItem.query.get_or_404(item_id)
    
    # Initialize cart in session
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    item_key = str(item_id)
    
    if item_key in cart:
        cart[item_key]['quantity'] += quantity
    else:
        cart[item_key] = {
            'id': item_id,
            'name': menu_item.name,
            'price': menu_item.price,
            'quantity': quantity,
            'vendor_id': menu_item.vendor_id
        }
    
    session['cart'] = cart
    session.modified = True
    
    return jsonify({'success': True, 'cart_count': len(cart)})

@app.route('/student/cart')
@login_required
@role_required('student')
def view_cart():
    cart = session.get('cart', {})
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    time_slots = get_available_time_slots()
    return render_template('student/cart.html', cart=cart, total=total, time_slots=time_slots)

@app.route('/student/update-cart', methods=['POST'])
@login_required
@role_required('student')
def update_cart():
    data = request.get_json()
    item_id = str(data.get('item_id'))
    action = data.get('action')
    
    cart = session.get('cart', {})
    
    if item_id in cart:
        if action == 'increase':
            cart[item_id]['quantity'] += 1
        elif action == 'decrease':
            cart[item_id]['quantity'] -= 1
            if cart[item_id]['quantity'] <= 0:
                del cart[item_id]
        elif action == 'remove':
            del cart[item_id]
    
    session['cart'] = cart
    session.modified = True
    
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    return jsonify({'success': True, 'total': total, 'cart_count': len(cart)})

@app.route('/student/checkout', methods=['POST'])
@login_required
@role_required('student')
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('student_home'))
    
    pickup_time = request.form.get('pickup_time')
    special_instructions = request.form.get('special_instructions', '')
    payment_method = request.form.get('payment_method')
    
    if not pickup_time:
        flash('Please select a pickup time', 'warning')
        return redirect(url_for('view_cart'))
    
    total_amount = sum(item['price'] * item['quantity'] for item in cart.values())
    
    # Get vendor_id from cart items (assuming all items from same vendor for MVP)
    vendor_id = list(cart.values())[0]['vendor_id']
    
    # Create order
    order_number = generate_order_number()
    order = Order(
        order_number=order_number,
        student_id=current_user.id,
        vendor_id=vendor_id,
        total_amount=total_amount,
        payment_method=payment_method,
        pickup_time=pickup_time,
        special_instructions=special_instructions,
        payment_status='pending' if payment_method == 'online' else 'cod',
        order_status='placed'
    )
    
    db.session.add(order)
    db.session.flush()  # Get order ID
    
    # Add order items
    for item in cart.values():
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item['id'],
            quantity=item['quantity'],
            price=item['price']
        )
        db.session.add(order_item)
    
    if payment_method == 'online':
        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(total_amount * 100),  # Amount in paise
            'currency': 'INR',
            'payment_capture': 1
        })
        order.razorpay_order_id = razorpay_order['id']
        db.session.commit()
        
        return render_template('student/checkout.html', 
                             order=order, 
                             razorpay_key=app.config['RAZORPAY_KEY_ID'],
                             razorpay_order_id=razorpay_order['id'])
    else:
        # COD - Generate QR code immediately
        qr_path = generate_qr_code(order_number, order.id)
        order.qr_code_path = qr_path
        order.payment_status = 'cod'
        db.session.commit()
        
        # Clear cart
        session['cart'] = {}
        session.modified = True
        
        # Notify vendor via SocketIO
        socketio.emit('new_order', {
            'order_id': order.id,
            'order_number': order_number
        }, room=f'vendor_{vendor_id}')
        
        return redirect(url_for('order_success', order_id=order.id))

@app.route('/student/payment-success', methods=['POST'])
@login_required
@role_required('student')
def payment_success():
    data = request.get_json()
    order_id = data.get('order_id')
    payment_id = data.get('payment_id')
    
    order = Order.query.get_or_404(order_id)
    order.razorpay_payment_id = payment_id
    order.payment_status = 'paid'
    
    # Generate QR code
    qr_path = generate_qr_code(order.order_number, order.id)
    order.qr_code_path = qr_path
    
    db.session.commit()
    
    # Clear cart
    session['cart'] = {}
    session.modified = True
    
    # Notify vendor
    socketio.emit('new_order', {
        'order_id': order.id,
        'order_number': order.order_number
    }, room=f'vendor_{order.vendor_id}')
    
    return jsonify({'success': True, 'redirect_url': url_for('order_success', order_id=order.id)})

@app.route('/student/order-success/<int:order_id>')
@login_required
@role_required('student')
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    if order.student_id != current_user.id:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('student_home'))
    return render_template('student/order_success.html', order=order)

@app.route('/student/my-orders')
@login_required
@role_required('student')
def my_orders():
    orders = Order.query.filter_by(student_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('student/my_orders.html', orders=orders)

# Vendor Routes
@app.route('/vendor/dashboard')
@login_required
@role_required('vendor')
def vendor_dashboard():
    pending_orders = Order.query.filter_by(vendor_id=current_user.id, order_status='placed').count()
    total_orders = Order.query.filter_by(vendor_id=current_user.id).count()
    menu_items = MenuItem.query.filter_by(vendor_id=current_user.id).count()
    return render_template('vendor/dashboard.html', 
                         pending_orders=pending_orders,
                         total_orders=total_orders,
                         menu_items=menu_items)

@app.route('/vendor/orders')
@login_required
@role_required('vendor')
def vendor_orders():
    status_filter = request.args.get('status', 'all')
    query = Order.query.filter_by(vendor_id=current_user.id)
    
    if status_filter != 'all':
        query = query.filter_by(order_status=status_filter)
    
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('vendor/orders.html', orders=orders, status_filter=status_filter)

@app.route('/vendor/update-order-status', methods=['POST'])
@login_required
@role_required('vendor')
def update_order_status():
    data = request.get_json()
    order_id = data.get('order_id')
    new_status = data.get('status')
    
    order = Order.query.get_or_404(order_id)
    
    if order.vendor_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    order.order_status = new_status
    db.session.commit()
    
    # Notify student via SocketIO
    socketio.emit('order_status_update', {
        'order_id': order.id,
        'status': new_status
    }, room=f'student_{order.student_id}')
    
    return jsonify({'success': True})

@app.route('/vendor/menu')
@login_required
@role_required('vendor')
def vendor_menu():
    menu_items = MenuItem.query.filter_by(vendor_id=current_user.id).all()
    return render_template('vendor/menu_management.html', menu_items=menu_items)

@app.route('/vendor/menu/add', methods=['GET', 'POST'])
@login_required
@role_required('vendor')
def add_menu_item():
    form = MenuItemForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        menu_item = MenuItem(
            name=form.name.data,
            description=form.description.data,
            price=form.price.data,
            category_id=form.category_id.data,
            vendor_id=current_user.id,
            is_available=form.is_available.data
        )
        db.session.add(menu_item)
        db.session.commit()
        flash('Menu item added successfully', 'success')
        return redirect(url_for('vendor_menu'))
    
    return render_template('vendor/menu_management.html', form=form, menu_items=[])

@app.route('/vendor/menu/toggle/<int:item_id>', methods=['POST'])
@login_required
@role_required('vendor')
def toggle_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    
    if item.vendor_id != current_user.id:
        return jsonify({'success': False}), 403
    
    item.is_available = not item.is_available
    db.session.commit()
    
    return jsonify({'success': True, 'is_available': item.is_available})

@app.route('/vendor/analytics')
@login_required
@role_required('vendor')
def vendor_analytics():
    orders = Order.query.filter_by(vendor_id=current_user.id).all()
    total_revenue = sum(o.total_amount for o in orders if o.payment_status in ['paid', 'cod'])
    
    return render_template('vendor/analytics.html', 
                         orders=orders,
                         total_revenue=total_revenue)

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        room = f'{current_user.role}_{current_user.id}'
        join_room(room)

# Initialize database and create default data
def init_db():
    with app.app_context():
        db.create_all()
        
        # Create default categories if they don't exist
        if Category.query.count() == 0:
            categories = [
                Category(name='Chai & Coffee', description='Hot beverages and tea'),
                Category(name='Snacks & Quick Bites', description='Vadapav, Samosa, and more'),
                Category(name='Main Course', description='Full meals and thalis'),
                Category(name='Drinks & Beverages', description='Cold drinks and juices')
            ]
            for category in categories:
                db.session.add(category)
            db.session.commit()
            print('Categories created successfully')

if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, port=5000)