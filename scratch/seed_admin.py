from app import create_app
from app.models import User, db
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    u1 = User.query.filter_by(username='admin').first()
    if not u1:
        u1 = User(username='admin', password_hash=generate_password_hash('44113290'), role='admin')
        db.session.add(u1)
    else:
        u1.password_hash = generate_password_hash('44113290')

    u2 = User.query.filter_by(username='admin@gmail.com').first()
    if u2:
        u2.password_hash = generate_password_hash('44113290')

    db.session.commit()
    print("Admin password for 'admin' and 'admin@gmail.com' updated to '44113290'.")
