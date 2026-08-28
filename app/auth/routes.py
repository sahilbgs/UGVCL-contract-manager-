import os
import time
from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models import User
from app.auth import auth

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('inventory.list_inventory'))
        return redirect(url_for('manager.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Login Successful!', 'success')
            if user.role == 'admin':
                return redirect(url_for('inventory.list_inventory'))
            return redirect(url_for('manager.dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('auth/login.html')

@auth.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

@auth.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')

@auth.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    full_name = request.form.get('full_name', '').strip()
    if not full_name:
        flash('Full Name is required.', 'danger')
        return redirect(url_for('auth.profile'))
        
    current_user.full_name = full_name
    
    # Handle Profile Picture upload
    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.gif']:
                filename = f"user_{current_user.id}_{int(time.time())}{ext}"
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'profile_pics')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                file.save(file_path)
                
                # Save path relative to uploads
                current_user.profile_pic = f"profile_pics/{filename}"
            else:
                flash('Unsupported image format. Please upload JPG, PNG, or GIF.', 'danger')
                return redirect(url_for('auth.profile'))
                
    try:
        db.session.commit()
        flash('Profile updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error: {str(e)}', 'danger')
        
    return redirect(url_for('auth.profile'))

@auth.route('/profile/update-password', methods=['POST'])
@login_required
def update_password():
    current_pass = request.form.get('current_password')
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    
    if not check_password_hash(current_user.password_hash, current_pass):
        flash('Incorrect current password.', 'danger')
        return redirect(url_for('auth.profile'))
        
    if not new_pass or len(new_pass) < 6:
        flash('New password must be at least 6 characters long.', 'danger')
        return redirect(url_for('auth.profile'))
        
    if new_pass != confirm_pass:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('auth.profile'))
        
    current_user.password_hash = generate_password_hash(new_pass)
    try:
        db.session.commit()
        flash('Password updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error: {str(e)}', 'danger')
        
    return redirect(url_for('auth.profile'))
