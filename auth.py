import os
from flask_login import LoginManager
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def seed_users():
    """Seeds admin and manager users from environment variables."""
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin@gmail.com')
    admin_pass = os.environ.get('ADMIN_PASSWORD')
    manager_user = os.environ.get('MANAGER_USERNAME', 'manager@gmail.com')
    manager_pass = os.environ.get('MANAGER_PASSWORD')

    if not admin_pass or not manager_pass:
        print("[WARNING] ADMIN_PASSWORD or MANAGER_PASSWORD environment variables not set. Using local development defaults.")
        admin_pass = admin_pass or 'admin_dev_pass_123'
        manager_pass = manager_pass or 'manager_dev_pass_123'

    try:
        # Seed Admin
        admin = User.query.filter_by(username=admin_user).first()
        if not admin:
            old_admin = User.query.filter_by(username='admin').first()
            if old_admin:
                db.session.delete(old_admin)
            hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
            admin = User(username=admin_user, password_hash=hashed_pw, role='admin')
            db.session.add(admin)
            
        # Seed Manager
        manager = User.query.filter_by(username=manager_user).first()
        if not manager:
            hashed_pw = generate_password_hash(manager_pass, method='pbkdf2:sha256')
            manager = User(username=manager_user, password_hash=hashed_pw, role='manager')
            db.session.add(manager)
            
        db.session.commit()
        print(f"Users verified/seeded: {admin_user} and {manager_user}")
    except Exception as e:
        print(f"Error seeding users: {e}")
        db.session.rollback()
