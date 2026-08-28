from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            flash("Permission Denied: Admin access required.", "danger")
            return redirect(url_for('manager.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
