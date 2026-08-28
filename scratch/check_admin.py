import sys; sys.path.insert(0, '.')
from app import create_app
app = create_app()
with app.app_context():
    from app.models import User
    from werkzeug.security import check_password_hash
    
    pw = "44113290"
    
    u = User.query.filter_by(username='admin').first()
    if u:
        check = check_password_hash(u.password_hash, pw)
        print(f"User admin (id={u.id}): password check = {check}")
    else:
        print("User admin not found!")
    
    u2 = User.query.filter_by(username='admin@gmail.com').first()
    if u2:
        check2 = check_password_hash(u2.password_hash, pw)
        print(f"User admin@gmail.com (id={u2.id}): password check = {check2}")
    else:
        print("User admin@gmail.com not found!")
