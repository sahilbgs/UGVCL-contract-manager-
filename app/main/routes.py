import os
from flask import render_template, redirect, url_for, send_from_directory, current_app
from flask_login import current_user, login_required
from app.main import main

@main.route('/')
def dashboard():
    """Root URL redirects based on role."""
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('inventory.list_inventory'))
        return redirect(url_for('manager.dashboard'))
    return redirect(url_for('auth.login'))

@main.route('/offline')
def offline():
    return render_template('offline.html')

@main.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@main.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    """Serve files securely from root uploads folder only for authenticated users."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
