from app import app, db
from models import User, Category, MenuItem

def add_sample_menu():
    with app.app_context():
        vendor = User.query.filter_by(role='vendor').first()
        
        if not vendor:
            print('✗ Please create a vendor first using add_vendor.py!')
            return
        
        # Check if menu items already exist
        existing_items = MenuItem.query.filter_by(vendor_id=vendor.id).count()
        if existing_items > 0:
            print(f'✓ Menu already has {existing_items} items')
            return
        
        categories = Category.query.all()
        
        sample_items = [
            # Chai & Coffee
            {'name': 'Masala Chai', 'price': 15.0, 'category': 'Chai & Coffee', 
             'description': 'Hot spiced tea with aromatic spices'},
            {'name': 'Coffee', 'price': 20.0, 'category': 'Chai & Coffee', 
             'description': 'Fresh brewed coffee'},
            {'name': 'Green Tea', 'price': 18.0, 'category': 'Chai & Coffee', 
             'description': 'Healthy green tea'},
            
            # Snacks
            {'name': 'Vada Pav', 'price': 25.0, 'category': 'Snacks & Quick Bites', 
             'description': 'Mumbai special vada pav with chutney'},
            {'name': 'Samosa Pav', 'price': 30.0, 'category': 'Snacks & Quick Bites', 
             'description': 'Crispy samosa with pav and chutney'},
            {'name': 'Misal Pav', 'price': 40.0, 'category': 'Snacks & Quick Bites', 
             'description': 'Spicy misal with pav'},
            {'name': 'Pav Bhaji', 'price': 50.0, 'category': 'Snacks & Quick Bites', 
             'description': 'Mumbai style pav bhaji'},
            {'name': 'Bhel Puri', 'price': 35.0, 'category': 'Snacks & Quick Bites', 
             'description': 'Tangy and crunchy bhel'},
            
            # Main Course
            {'name': 'Veg Thali', 'price': 80.0, 'category': 'Main Course', 
             'description': 'Complete meal with rice, roti, dal, sabzi, salad'},
            {'name': 'Paneer Butter Masala', 'price': 100.0, 'category': 'Main Course', 
             'description': 'Paneer in rich tomato gravy with 2 rotis'},
            {'name': 'Dal Fry with Rice', 'price': 60.0, 'category': 'Main Course', 
             'description': 'Tempered dal with steamed rice'},
            {'name': 'Chole Bhature', 'price': 70.0, 'category': 'Main Course', 
             'description': 'Spicy chole with fluffy bhature'},
            
            # Drinks
            {'name': 'Cold Coffee', 'price': 40.0, 'category': 'Drinks & Beverages', 
             'description': 'Chilled coffee with ice cream'},
            {'name': 'Mango Juice', 'price': 30.0, 'category': 'Drinks & Beverages', 
             'description': 'Fresh mango juice'},
            {'name': 'Lemon Soda', 'price': 25.0, 'category': 'Drinks & Beverages', 
             'description': 'Refreshing lemon soda'},
            {'name': 'Buttermilk', 'price': 20.0, 'category': 'Drinks & Beverages', 
             'description': 'Cool and refreshing chaas'},
        ]
        
        added_count = 0
        for item_data in sample_items:
            category = Category.query.filter_by(name=item_data['category']).first()
            if category:
                item = MenuItem(
                    name=item_data['name'],
                    description=item_data['description'],
                    price=item_data['price'],
                    category_id=category.id,
                    vendor_id=vendor.id,
                    is_available=True
                )
                db.session.add(item)
                added_count += 1
        
        db.session.commit()
        print(f'✓ Successfully added {added_count} sample menu items!')
        print('─' * 40)
        print('Menu items added to categories:')
        for cat in categories:
            count = MenuItem.query.filter_by(category_id=cat.id, vendor_id=vendor.id).count()
            print(f'  • {cat.name}: {count} items')
        print('─' * 40)

if __name__ == '__main__':
    add_sample_menu()