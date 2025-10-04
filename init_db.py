"""
Database initialization script for SkipTheQueue
Run this script to create the database and default categories
"""

from app import app, db
from models import Category

def init_database():
    with app.app_context():
        print('Creating database tables...')
        db.create_all()
        print('✓ Database tables created')
        
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
            print('✓ Default categories created')
            print('─' * 40)
            print('Categories:')
            for cat in Category.query.all():
                print(f'  • {cat.name}: {cat.description}')
            print('─' * 40)
        else:
            print('✓ Categories already exist')
        
        print('\n✅ Database initialization complete!')
        print('\nNext steps:')
        print('  1. Run: python add_vendor.py')
        print('  2. Run: python add_sample_menu.py (optional)')
        print('  3. Run: python app.py')

if __name__ == '__main__':
    init_database()