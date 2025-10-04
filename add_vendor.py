from app import app, db
from models import User

def add_vendor():
    with app.app_context():
        # Check if vendor exists
        vendor = User.query.filter_by(email='vendor@somaiya.edu').first()
        
        if not vendor:
            vendor = User(
                email='vendor@somaiya.edu',
                full_name='Campus Canteen',
                phone='9876543210',
                role='vendor'
            )
            vendor.set_password('vendor123')
            db.session.add(vendor)
            db.session.commit()
            print('✓ Vendor created successfully!')
            print('─' * 40)
            print('Login Credentials:')
            print('Email: vendor@somaiya.edu')
            print('Password: vendor123')
            print('─' * 40)
        else:
            print('✗ Vendor already exists')
            print('Email: vendor@somaiya.edu')

if __name__ == '__main__':
    add_vendor()