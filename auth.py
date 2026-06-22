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
    """Seeds default admin and manager users."""
    try:
        # Seed Admin
        admin = User.query.filter_by(username='admin@gmail.com').first()
        if not admin:
            old_admin = User.query.filter_by(username='admin').first()
            if old_admin:
                db.session.delete(old_admin)
            hashed_pw = generate_password_hash('44113290', method='pbkdf2:sha256')
            admin = User(username='admin@gmail.com', password_hash=hashed_pw, role='admin')
            db.session.add(admin)
            
        # Seed Manager
        manager = User.query.filter_by(username='manager@gmail.com').first()
        if not manager:
            hashed_pw = generate_password_hash('44113290', method='pbkdf2:sha256')
            manager = User(username='manager@gmail.com', password_hash=hashed_pw, role='manager')
            db.session.add(manager)
            
        db.session.commit()
        print("Default users seeded: admin@gmail.com and manager@gmail.com")
    except Exception as e:
        print(f"Error seeding users: {e}")
        db.session.rollback()
