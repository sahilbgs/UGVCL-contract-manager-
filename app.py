import os
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from decimal import Decimal
from datetime import datetime, date
import json
import re

# Load models and auth
from models import db, User, WorkOrder, ReleaseOrder, Material, MaterialReceipt, MaterialReceiptItem, CreditReceipt, DocumentVault
from auth import login_manager, seed_users
from ocr_parser import parse_gate_pass_image

from flask_wtf.csrf import CSRFProtect

# Load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# Security: Secret key enforcement
secret_key = os.environ.get('SECRET_KEY')
flask_env = os.environ.get('FLASK_ENV', 'development')

if not secret_key:
    if flask_env == 'production':
        raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is missing in production environment!")
    else:
        print("[WARNING] SECRET_KEY not found in environment. Falling back to development secret key.")
        secret_key = 'dev-fallback-secret-key-ugvcl-do-not-use-in-prod'

app.config['SECRET_KEY'] = secret_key
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload limit

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Database configuration: support MySQL if configured in environment, fallback to SQLite
db_host = os.environ.get('MYSQL_HOST', 'localhost')
db_user = os.environ.get('MYSQL_USER', '')
db_pass = os.environ.get('MYSQL_PASSWORD', '')
db_name = os.environ.get('MYSQL_DATABASE', 'ugvcl_contract_manager')

import sys
is_testing = 'pytest' in sys.modules or 'unittest' in sys.modules or os.environ.get('FLASK_ENV') == 'testing' or os.environ.get('TESTING') == 'True'

if is_testing:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
elif db_user:
    # Use MySQL
    import urllib.parse
    encoded_pass = urllib.parse.quote_plus(db_pass)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{db_user}:{encoded_pass}@{db_host}/{db_name}"
else:
    # Fallback to local SQLite in workspace
    if flask_env == 'production':
        print("[CRITICAL WARNING] Running SQLite in production mode! High risk of database write concurrency locks.")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ugvcl_contract_manager.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload folders configuration
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Initialize db and login manager
db.init_app(app)
login_manager.init_app(app)


from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'admin':
            flash("Permission Denied: Admin access required.", "danger")
            return redirect(url_for('manager_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

COMMON_MATERIALS = [
    ("Conducto 34mm 2wire", "Mtr", "0102000031"),
    ("Conductor 34mm 5wire", "Mtr", "0102000031"),
    ("PSC Pole 8 MTR", "Nos", "2611000003"),
    ("PSC Pole 10 MTR", "Nos", "2611000010"),
    ("Three Hole Parties", "Nos", None),
    ("V-x arm", "Nos", "2609000034"),
    ("Top Fitting", "Nos", "2601000084"),
    ("Side Clamp", "Nos", "2601000049"),
    ("Earthing Plate/Coil", "Nos", "0901000024"),
    ("G.I. Wire 8 No.", "Kg", "0103000002"),
    ("Stay Wire 7/12", "Kg", "0103000014"),
    ("Stay Clamp Pair", "Pair", "2601000069"),
    ("Turn Buckle", "Nos", "2614000009"),
    ("Eye Bolt", "Nos", "2614000012"),
    ("Stay Insulator", "Nos", "2003000001"),
    ("Anchor Road", "Nos", "2614000002"),
    ("C.C. Block", "Nos", "2614000013"),
    ("U CLAIMP", "Nos", "2601000040"),
    ("LT SHACKLE", "Nos", "2002000001"),
    ("PVC PIPE", "Nos", "2801000016"),
    ("Bolt-2.6\"(with nut)", "Nos", "2010000002"),
    ("Bolt-5.0\"(with nut)", "Nos", "2010000002"),
    ("Bolt-7.0\"(with nut)", "Nos", "2010000002"),
    ("Bolt-11.0\"(with nut)", "Nos", "2010000002"),
    
    # Other items
    ("Conductor 34mm  4wire", "Mtr", "0102000031"),
    ("Conductor 55 mm 3wire", "Mtr", "0102000033"),
    ("Transformer 10 KVA", "Nos", None),
    ("Transformer 25 KVA", "Nos", None),
    ("Transformer 63 KVA", "Nos", None),
    ("11kv Comp Pin Insulator", "Nos", "2001000010"),
    ("11kv Pin Insulator", "Nos", "2001000010"),
    ("11kv G.I. Pin", "Nos", "2010000010"),
    ("11kv Shackle Insulator", "Nos", "2006000006"),
    ("11kv Shackle H/W", "Set.", "2010000077"),
    ("Angle 9' Fut(65*65*6)", "Fut", None),
    ("Angle 9' Fut(50*50*6)", "Fut", None),
    ("Angle 4' Fut", "Fut", None),
    ("Angle 2'.6'' Fut", "Fut", None),
    ("11kv D.O Angle / Fuse", "Nos", None),
    ("L.A ", "Nos", None),
    ("MS Chanal-6 fut", "Nos", None),
]

SEED_MAPPINGS = [
    ('u clamp', '2601000040'),
    ('c clamp', '2601000040'),
    ('u claimp', '2601000040'),
    ('lt shackle', '2002000001'),
    ('shackle insulator', '2002000001'),
    ('440v lt shackle', '2002000001'),
    ('440 v lt shackle', '2002000001'),
    ('earthing coil', '0901000024'),
    ('gi earthing coil', '0901000024'),
    ('earthing plate/coil', '0901000024'),
    ('pvc pipe', '2801000016'),
    ('hd rigid pvc', '2801000016'),
    ('h d rigid pvc', '2801000016'),
    ('wire 8', '0103000002'),
    ('wire no.8', '0103000002'),
    ('wire no. 8', '0103000002'),
    ('gi wire 8', '0103000002'),
    ('gi wire no.8', '0103000002'),
    ('gi wire no. 8', '0103000002'),
    ('conductor 34', '0102000031'),
    ('conducto 34', '0102000031'),
    ('weasel', '0102000031'),
    ('alloy conductor 34', '0102000031'),
    ('aluminium alloy conductor 34', '0102000031'),
    ('stay clamp', '2601000069'),
    ('stay clamp pair', '2601000069'),
    ('anchor rod', '2614000002'),
    ('anchor road', '2614000002'),
    ('turn buckle', '2614000009'),
    ('eye bolt', '2614000012'),
    ('guy insulator', '2003000001'),
    ('stay insulator', '2003000001'),
    ('stay insulator ht', '2003000001'),
    ('pole 8', '2611000003'),
    ('pole-8', '2611000003'),
    ('psc pole 8', '2611000003'),
    ('psc pole-8', '2611000003'),
    ('pole 10', '2611000010'),
    ('pole-10', '2611000010'),
    ('psc pole 10', '2611000010'),
    ('psc pole-10', '2611000010'),
    ('earthing plate', '0901000007'),
    ('wire 10', '0103000003'),
    ('wire no.10', '0103000003'),
    ('wire no. 10', '0103000003'),
    ('gi wire 10', '0103000003'),
    ('gi wire no.10', '0103000003'),
    ('gi wire no. 10', '0103000003'),
    ('cc block', '2614000013'),
    ('c.c.block', '2614000013'),
    ('block', '2614000013'),
    ('stay wire 7/12', '0103000014'),
    ('stay wire', '0103000014'),
    ('conductor 55', '0102000033'),
    ('conducto 55', '0102000033'),
    ('alloy conductor 55', '0102000033'),
    ('side clamp', '2601000049'),
    ('v-cross', '2609000034'),
    ('v cross', '2609000034'),
    ('vcross', '2609000034'),
    ('top fitting', '2601000084'),
    ('comp pin insulator', '2001000010'),
    ('pin insulator', '2001000010'),
    ('gi pin', '2010000010'),
    ('g.i.pin', '2010000010'),
    ('11kv shackle insulator', '2006000006'),
    ('11kv shackle hard ware', '2010000077'),
    ('11kv shackle h/w', '2010000077'),
    ('shackle hard ware', '2010000077'),
    ('shackle h/w', '2010000077'),
    ('bolts + nuts', '2010000002'),
    ('bolts & nuts', '2010000002'),
    ('gi bolts', '2010000002'),
    ('g.i. bolts', '2010000002'),
    ('bolt-2.6', '2010000002'),
    ('bolt-5.0', '2010000002'),
    ('bolt-7.0', '2010000002'),
    ('bolt-11.0', '2010000002'),
]

def seed_materials():
    """Seeds typical material items and alias mappings into the database."""
    try:
        # Seed Materials
        for name, unit, code in COMMON_MATERIALS:
            m = Material.query.filter_by(name=name).first()
            if not m:
                new_m = Material(name=name, unit=unit, opening_stock=0.0, item_code=code)
                db.session.add(new_m)
            else:
                if code and not m.item_code:
                    m.item_code = code
        db.session.commit()
        
        # Seed Mappings
        from models import MaterialMapping
        for alias, item_code in SEED_MAPPINGS:
            existing = MaterialMapping.query.filter_by(alias=alias).first()
            if not existing:
                new_map = MaterialMapping(alias=alias, item_code=item_code)
                db.session.add(new_map)
        db.session.commit()
    except Exception as e:
        print(f"Error seeding materials/mappings: {e}")
        db.session.rollback()

def migrate_database():
    """Database-agnostic migration helper to add columns to existing database tables."""
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        
        # Check materials table for item_code
        columns = [c['name'] for c in inspector.get_columns('materials')]
        if 'item_code' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE materials ADD COLUMN item_code VARCHAR(50)"))
            
        # Check farmers table for po_no and release_no
        columns = [c['name'] for c in inspector.get_columns('farmers')]
        if 'po_no' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE farmers ADD COLUMN po_no VARCHAR(50)"))
        if 'release_no' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE farmers ADD COLUMN release_no VARCHAR(50)"))
                
        # Check release_orders table for status
        columns = [c['name'] for c in inspector.get_columns('release_orders')]
        if 'status' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE release_orders ADD COLUMN status VARCHAR(50) DEFAULT 'Pending'"))

        # Check users table for role, full_name, and profile_pic
        columns = [c['name'] for c in inspector.get_columns('users')]
        if 'role' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'manager'"))
        if 'full_name' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(100)"))
        if 'profile_pic' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN profile_pic VARCHAR(255)"))

        # Check farmer_materials table for pole_no and item_code
        columns = [c['name'] for c in inspector.get_columns('farmer_materials')]
        if 'pole_no' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE farmer_materials ADD COLUMN pole_no VARCHAR(50)"))
        if 'item_code' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE farmer_materials ADD COLUMN item_code VARCHAR(50)"))
    except Exception as e:
        print(f"Migration error: {e}")


def resolve_item_code_from_name(name):
    """Resolves standard UGVCL material name variation to its 10-digit item_code using DB mapping."""
    if not name:
        return None
    name_lower = name.lower().strip()
    
    try:
        from models import MaterialMapping
        # Match exactly first
        mapping = MaterialMapping.query.filter_by(alias=name_lower).first()
        if mapping:
            return mapping.item_code
            
        # Match substring (if alias is contained in the material name)
        # Sort by length desc so longer matches (more specific) take precedence
        mappings = MaterialMapping.query.all()
        sorted_mappings = sorted(mappings, key=lambda x: len(x.alias), reverse=True)
        for m in sorted_mappings:
            if m.alias in name_lower:
                return m.item_code
    except Exception as e:
        print(f"Error resolving item code from DB: {e}")
        
    return None

def find_material_by_code_or_name(item_code, name):
    """Find a Material by item_code first, then fallback to name."""
    if not item_code and name:
        item_code = resolve_item_code_from_name(name)
        
    if item_code:
        m = Material.query.filter_by(item_code=item_code).first()
        if m:
            return m
    return Material.query.filter_by(name=name).first()


# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('inventory'))
        return redirect(url_for('manager_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Login Successful!', 'success')
            if user.role == 'admin':
                return redirect(url_for('inventory'))
            return redirect(url_for('manager_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    full_name = request.form.get('full_name', '').strip()
    if not full_name:
        flash('Full Name is required.', 'danger')
        return redirect(url_for('profile'))
        
    current_user.full_name = full_name
    
    # Handle Profile Picture upload
    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and file.filename != '':
            # Validate extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.gif']:
                # Save file
                filename = f"user_{current_user.id}_{int(time.time())}{ext}"
                upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                file.save(file_path)
                
                # Save relative path to DB
                current_user.profile_pic = f"/static/uploads/profile_pics/{filename}"
            else:
                flash('Unsupported image format. Please upload JPG, PNG, or GIF.', 'danger')
                return redirect(url_for('profile'))
                
    try:
        db.session.commit()
        flash('Profile updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error: {str(e)}', 'danger')
        
    return redirect(url_for('profile'))

@app.route('/profile/update-password', methods=['POST'])
@login_required
def update_password():
    current_pass = request.form.get('current_password')
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    
    if not check_password_hash(current_user.password_hash, current_pass):
        flash('Incorrect current password.', 'danger')
        return redirect(url_for('profile'))
        
    if not new_pass or len(new_pass) < 6:
        flash('New password must be at least 6 characters long.', 'danger')
        return redirect(url_for('profile'))
        
    if new_pass != confirm_pass:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('profile'))
        
    current_user.password_hash = generate_password_hash(new_pass)
    try:
        db.session.commit()
        flash('Password updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error: {str(e)}', 'danger')
        
    return redirect(url_for('profile'))

@app.route('/')
def dashboard():
    """Root URL redirects based on role."""
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('inventory'))
        return redirect(url_for('manager_dashboard'))
    return redirect(url_for('login'))

# ===================== WORK ORDER ROUTES =====================

@app.route('/work-orders', methods=['GET', 'POST'])
@admin_required
def work_orders_list():
    if request.method == 'POST':
        work_order_no = request.form.get('work_order_no')
        po_no = request.form.get('po_no')
        tender_id = request.form.get('tender_id')
        rfq_no = request.form.get('rfq_no')
        pr_no = request.form.get('pr_no')
        approval_no = request.form.get('approval_no')
        contractor_name = request.form.get('contractor_name')
        contract_amount_str = request.form.get('contract_amount')
        
        # Parse amount
        try:
            contract_amount = Decimal(contract_amount_str)
        except (ValueError, TypeError):
            contract_amount = Decimal('0.00')
            
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        
        # Handle file upload if any
        pdf_file = request.files.get('pdf_file')
        pdf_path = None
        if pdf_file and pdf_file.filename != '':
            filename = secure_filename(pdf_file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(file_path)
            pdf_path = f"/static/uploads/{filename}"
            
        # Create work order
        wo = WorkOrder(
            work_order_no=work_order_no,
            po_no=po_no,
            tender_id=tender_id,
            rfq_no=rfq_no,
            pr_no=pr_no,
            approval_no=approval_no,
            contractor_name=contractor_name,
            contract_amount=contract_amount,
            balance_amount=contract_amount, # balance starts as contract amount
            start_date=start_date,
            end_date=end_date,
            pdf_path=pdf_path
        )
        db.session.add(wo)
        
        if pdf_path:
            # Also add to DocumentVault
            vault_doc = DocumentVault(
                doc_type='Work Order',
                filename=secure_filename(pdf_file.filename),
                file_path=pdf_path
            )
            db.session.add(vault_doc)
            db.session.flush() # get vault_doc.id or link later
            
        try:
            db.session.commit()
            if pdf_path and 'vault_doc' in locals() and vault_doc:
                vault_doc.related_id = wo.id
                db.session.commit()
            flash(f'Work Order {work_order_no} created successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating Work Order: {str(e)}', 'danger')
            
        return redirect(url_for('work_orders_list'))
        
    work_orders = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    
    # Calculate aggregate stats
    total_contract_amount = sum(wo.contract_amount for wo in work_orders)
    total_balance_amount = sum(wo.balance_amount for wo in work_orders)
    
    return render_template('work_orders.html', 
                           work_orders=work_orders, 
                           total_contract_amount=total_contract_amount, 
                           total_balance_amount=total_balance_amount)

@app.route('/work-orders/upload', methods=['POST'])
@admin_required
def work_orders_upload():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        from ocr_parser import parse_work_order_pdf
        parsed_data = parse_work_order_pdf(file_path)
        
        # Save to DocumentVault as temporary/unlinked
        vault_doc = DocumentVault(
            doc_type='Work Order PDF',
            filename=filename,
            file_path=f"/static/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        parsed_data['success'] = True
        parsed_data['vault_doc_id'] = vault_doc.id
        parsed_data['file_path'] = f"/static/uploads/{filename}"
        
        # Convert date to string format for javascript input[type="date"]
        if parsed_data.get('start_date'):
            parsed_data['start_date'] = parsed_data['start_date'].strftime('%Y-%m-%d')
        if parsed_data.get('end_date'):
            parsed_data['end_date'] = parsed_data['end_date'].strftime('%Y-%m-%d')
            
        return jsonify(parsed_data)
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@app.route('/work-orders/save-ocr', methods=['POST'])
@admin_required
def work_orders_save_ocr():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        work_order_no = data.get('work_order_no')
        po_no = data.get('po_no')
        tender_id = data.get('tender_id')
        rfq_no = data.get('rfq_no')
        pr_no = data.get('pr_no')
        approval_no = data.get('approval_no')
        contractor_name = data.get('contractor_name')
        
        try:
            contract_amount = Decimal(str(data.get('contract_amount', '0')))
        except (ValueError, TypeError):
            contract_amount = Decimal('0.00')
            
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        
        vault_doc_id = data.get('vault_doc_id')
        pdf_path = data.get('pdf_path')
        
        # Create WorkOrder
        wo = WorkOrder(
            work_order_no=work_order_no,
            po_no=po_no,
            tender_id=tender_id,
            rfq_no=rfq_no,
            pr_no=pr_no,
            approval_no=approval_no,
            contractor_name=contractor_name,
            contract_amount=contract_amount,
            balance_amount=contract_amount,
            start_date=start_date,
            end_date=end_date,
            pdf_path=pdf_path
        )
        db.session.add(wo)
        db.session.flush() # get ID
        
        if vault_doc_id:
            vault_doc = DocumentVault.query.get(vault_doc_id)
            if vault_doc:
                vault_doc.related_id = wo.id
                vault_doc.doc_type = 'Work Order'
                
        db.session.commit()
        flash(f'Work Order {work_order_no} created successfully from PDF!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/work-orders/details/<int:wo_id>', methods=['GET'])
@admin_required
def work_order_details(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        
        # serialize release orders
        ros = []
        for ro in wo.release_orders:
            ros.append({
                'release_no': ro.release_no,
                'release_date': ro.release_date.strftime('%Y-%m-%d') if ro.release_date else 'N/A',
                'po_no': ro.po_no,
                'release_amount': float(ro.release_amount),
                'remaining_amount': float(ro.remaining_amount) if ro.remaining_amount is not None else 0.0,
                'scheme': ro.scheme,
                'pdf_path': ro.pdf_path
            })
            
        data = {
            'success': True,
            'id': wo.id,
            'work_order_no': wo.work_order_no,
            'po_no': wo.po_no,
            'tender_id': wo.tender_id,
            'rfq_no': wo.rfq_no,
            'pr_no': wo.pr_no,
            'approval_no': wo.approval_no,
            'contractor_name': wo.contractor_name,
            'contract_amount': float(wo.contract_amount),
            'balance_amount': float(wo.balance_amount),
            'start_date': wo.start_date.strftime('%d-%b-%Y') if wo.start_date else 'N/A',
            'end_date': wo.end_date.strftime('%d-%b-%Y') if wo.end_date else 'N/A',
            'pdf_path': wo.pdf_path,
            'release_orders': ros
        }
        return jsonify(data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/work-orders/<int:wo_id>', methods=['GET'])
@admin_required
def work_order_view(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        return render_template('work_order_details.html', wo=wo)
    except Exception as e:
        flash(f"Error loading Work Order: {str(e)}", "danger")
        return redirect(url_for('work_orders_list'))

@app.route('/work-orders/delete/<int:wo_id>', methods=['POST'])
@admin_required
def work_orders_delete(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    try:
        DocumentVault.query.filter(
            (DocumentVault.related_id == wo.id) & 
            ((DocumentVault.doc_type == 'Work Order') | (DocumentVault.doc_type == 'Work Order PDF'))
        ).delete()
        
        db.session.delete(wo)
        db.session.commit()
        flash('Work Order and associated Release Orders deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting Work Order: {e}', 'danger')
    return redirect(url_for('work_orders_list'))

@app.route('/work-orders/add-release-order', methods=['POST'])
@admin_required
def add_release_order():
    work_order_id = request.form.get('work_order_id')
    release_no = request.form.get('release_no')
    po_no = request.form.get('po_no')
    release_amount_str = request.form.get('release_amount')
    scheme = request.form.get('scheme')
    release_date_str = request.form.get('release_date')
    
    # Parse release amount
    try:
        release_amount = Decimal(release_amount_str)
    except (ValueError, TypeError):
        release_amount = Decimal('0.00')
        
    release_date = datetime.strptime(release_date_str, '%Y-%m-%d').date() if release_date_str else None
    
    # Optional PDF upload
    pdf_file = request.files.get('pdf_file')
    pdf_path = None
    if pdf_file and pdf_file.filename != '':
        filename = secure_filename(pdf_file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        pdf_file.save(file_path)
        pdf_path = f"/static/uploads/{filename}"
        
    wo = WorkOrder.query.get_or_404(work_order_id)
    
    # Create Release Order
    ro = ReleaseOrder(
        work_order_id=wo.id,
        release_no=release_no,
        release_date=release_date,
        po_no=po_no,
        release_amount=release_amount,
        remaining_amount=release_amount,
        scheme=scheme,
        pdf_path=pdf_path
    )
    db.session.add(ro)
    
    # Deduct parent Work Order balance
    wo.balance_amount = max(Decimal('0.00'), wo.balance_amount - release_amount)
    
    if pdf_path:
        vault_doc = DocumentVault(
            doc_type='Release Order',
            filename=secure_filename(pdf_file.filename),
            file_path=pdf_path
        )
        db.session.add(vault_doc)
        db.session.flush()
        
        # Try to parse combined materials and farmers
        try:
            from ocr_parser import parse_release_order_pdf
            parsed_data = parse_release_order_pdf(file_path)
            
            # Save associated materials list (Page 2) if present
            materials_data = parsed_data.get('materials', [])
            if materials_data:
                receipt_no = parsed_data.get('receipt_no') or f"MR-RO-{release_no}"
                from ocr_parser import normalize_mr_number
                receipt_no = normalize_mr_number(receipt_no)
                
                existing_receipt = MaterialReceipt.query.filter_by(release_order_id=ro.id, receipt_no=receipt_no).first()
                if not existing_receipt:
                    receipt = MaterialReceipt(
                        release_order_id=ro.id,
                        receipt_no=receipt_no,
                        date=release_date or date.today()
                    )
                    db.session.add(receipt)
                    db.session.flush()
                    
                    for mat_item in materials_data:
                        m_name = mat_item.get('material_name')
                        qty = Decimal(str(mat_item.get('qty', '0.0')))
                        item_code = mat_item.get('item_code')
                        
                        if qty > 0:
                            m = find_material_by_code_or_name(item_code, m_name)
                            
                            # Sub-work order materials list is NOT a material receipt, do not increment received_qty
                            
                            item = MaterialReceiptItem(
                                receipt_id=receipt.id,
                                material_name=m.name if m else m_name,
                                qty=qty,
                                rate=0.0
                            )
                            db.session.add(item)
                            
            # Save associated farmers list (Page 3) if present
            farmers_data = parsed_data.get('farmers', [])
            if farmers_data:
                from models import Farmer, FarmerMaterial
                for fd in farmers_data:
                    sr_number = fd.get('sr_number') or f"GEN-{datetime.utcnow().timestamp()}"
                    applicant_name = fd.get('applicant_name', 'UNKNOWN')
                    village = fd.get('village', 'UNKNOWN')
                    
                    f_date_str = fd.get('date')
                    from ocr_parser import parse_date
                    parsed_date = parse_date(f_date_str) if f_date_str else release_date
                    
                    ht = Decimal(str(fd.get('ht', '0.0')))
                    lt4 = Decimal(str(fd.get('lt4', '0.0')))
                    lt2 = Decimal(str(fd.get('lt2', '0.0')))
                    tc = int(fd.get('tc', 0))
                    ex = Decimal(str(fd.get('ex', '0.0')))
                    
                    farmer = Farmer(
                        release_order_id=ro.id,
                        sr_number=sr_number,
                        applicant_name=applicant_name,
                        village=village,
                        date=parsed_date,
                        ht=ht,
                        lt4=lt4,
                        lt2=lt2,
                        tc=tc,
                        ex=ex,
                        status='Pending',
                        po_no=ro.po_no,
                        release_no=ro.release_no
                    )
                    db.session.add(farmer)
                    db.session.flush()
                    
                    # Get any explicitly provided materials (no auto-estimation)
                    materials = fd.get('materials', {})
                    
                    for m_name, qty_val in materials.items():
                        qty = Decimal(str(qty_val))
                        resolved_code = resolve_item_code_from_name(m_name)
                        m = find_material_by_code_or_name(resolved_code, m_name)
                        
                        fm = FarmerMaterial(
                            farmer_id=farmer.id,
                            material_name=m.name if m else m_name,
                            item_code=m.item_code if m else resolved_code,
                            qty_required=qty,
                            qty_issued=0.0,
                            qty_consumed=0.0
                        )
                        db.session.add(fm)
        except Exception as ocr_err:
            print(f"OCR auto-parsing failed for manual upload: {ocr_err}")
            
    try:
        db.session.commit()
        if pdf_path and 'vault_doc' in locals() and vault_doc:
            vault_doc.related_id = ro.id
            db.session.commit()
        flash(f'Sub-Work Order (Release #{release_no}) added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding Sub-Work Order: {str(e)}', 'danger')
        
    return redirect(url_for('work_order_view', wo_id=wo.id))

@app.route('/work-orders/upload-release-order', methods=['POST'])
@admin_required
def upload_release_order():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        from ocr_parser import parse_release_order_pdf
        parsed_data = parse_release_order_pdf(file_path)
        
        # Save to vault temporarily
        vault_doc = DocumentVault(
            doc_type='Release Order PDF',
            filename=filename,
            file_path=f"/static/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        parsed_data['success'] = True
        parsed_data['vault_doc_id'] = vault_doc.id
        parsed_data['file_path'] = f"/static/uploads/{filename}"
        
        if parsed_data.get('release_date'):
            parsed_data['release_date'] = parsed_data['release_date'].strftime('%Y-%m-%d')
            
        return jsonify(parsed_data)
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@app.route('/work-orders/save-release-order-ocr', methods=['POST'])
@admin_required
def save_release_order_ocr():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        work_order_id = data.get('work_order_id')
        release_no = data.get('release_no')
        po_no = data.get('po_no')
        
        try:
            release_amount = Decimal(str(data.get('release_amount', '0')))
        except (ValueError, TypeError):
            release_amount = Decimal('0.00')
            
        try:
            remaining_amount = Decimal(str(data.get('remaining_amount', str(release_amount))))
        except (ValueError, TypeError):
            remaining_amount = release_amount
            
        scheme = data.get('scheme')
        release_date_str = data.get('release_date')
        # Handle datetime format from javascript or backend
        if release_date_str:
            if 'T' in release_date_str:
                release_date = datetime.strptime(release_date_str.split('T')[0], '%Y-%m-%d').date()
            else:
                release_date = datetime.strptime(release_date_str, '%Y-%m-%d').date()
        else:
            release_date = None
        
        vault_doc_id = data.get('vault_doc_id')
        pdf_path = data.get('pdf_path')
        
        wo = WorkOrder.query.get_or_404(work_order_id)
        
        # Create ReleaseOrder
        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no=release_no,
            release_date=release_date,
            po_no=po_no,
            release_amount=release_amount,
            remaining_amount=remaining_amount,
            scheme=scheme,
            pdf_path=pdf_path
        )
        db.session.add(ro)
        
        # Deduct parent Work Order balance
        wo.balance_amount = max(Decimal('0.00'), wo.balance_amount - release_amount)
        db.session.flush() # get ID
        
        # Save associated materials list (Page 2) if present
        materials_data = data.get('materials', [])
        if materials_data:
            receipt_no = data.get('receipt_no') or f"MR-RO-{release_no}"
            from ocr_parser import normalize_mr_number
            receipt_no = normalize_mr_number(receipt_no)
            
            existing_receipt = MaterialReceipt.query.filter_by(release_order_id=ro.id, receipt_no=receipt_no).first()
            if not existing_receipt:
                receipt = MaterialReceipt(
                    release_order_id=ro.id,
                    receipt_no=receipt_no,
                    date=release_date or date.today()
                )
                db.session.add(receipt)
                db.session.flush()
                
                for mat_item in materials_data:
                    m_name = mat_item.get('material_name')
                    qty = Decimal(str(mat_item.get('qty', '0.0')))
                    item_code = mat_item.get('item_code')
                    
                    if qty > 0:
                        m = find_material_by_code_or_name(item_code, m_name)
                        
                        # Sub-work order materials list is NOT a material receipt, do not increment received_qty
                        
                        item = MaterialReceiptItem(
                            receipt_id=receipt.id,
                            material_name=m.name if m else m_name,
                            qty=qty,
                            rate=0.0
                        )
                        db.session.add(item)
                        
        # Save associated farmers list (Page 3) if present
        farmers_data = data.get('farmers', [])
        if farmers_data:
            from models import Farmer, FarmerMaterial
            for fd in farmers_data:
                sr_number = fd.get('sr_number') or f"GEN-{datetime.utcnow().timestamp()}"
                applicant_name = fd.get('applicant_name', 'UNKNOWN')
                village = fd.get('village', 'UNKNOWN')
                
                f_date_str = fd.get('date')
                from ocr_parser import parse_date
                parsed_date = parse_date(f_date_str) if f_date_str else release_date
                
                ht = Decimal(str(fd.get('ht', '0.0')))
                lt4 = Decimal(str(fd.get('lt4', '0.0')))
                lt2 = Decimal(str(fd.get('lt2', '0.0')))
                tc = int(fd.get('tc', 0))
                ex = Decimal(str(fd.get('ex', '0.0')))
                
                farmer = Farmer(
                    release_order_id=ro.id,
                    sr_number=sr_number,
                    applicant_name=applicant_name,
                    village=village,
                    date=parsed_date,
                    ht=ht,
                    lt4=lt4,
                    lt2=lt2,
                    tc=tc,
                    ex=ex,
                    status='Pending',
                    po_no=ro.po_no,
                    release_no=ro.release_no
                )
                db.session.add(farmer)
                db.session.flush()
                
                # Get any explicitly provided materials (no auto-estimation)
                materials = fd.get('materials', {})
                
                for m_name, qty_val in materials.items():
                    qty = Decimal(str(qty_val))
                    resolved_code = resolve_item_code_from_name(m_name)
                    m = find_material_by_code_or_name(resolved_code, m_name)
                    
                    fm = FarmerMaterial(
                        farmer_id=farmer.id,
                        material_name=m.name if m else m_name,
                        item_code=m.item_code if m else resolved_code,
                        qty_required=qty,
                        qty_issued=0.0,
                        qty_consumed=0.0
                    )
                    db.session.add(fm)
        
        if vault_doc_id:
            vault_doc = DocumentVault.query.get(vault_doc_id)
            if vault_doc:
                vault_doc.related_id = ro.id
                vault_doc.doc_type = 'Release Order'
                
        db.session.commit()
        flash(f'Sub-Work Order (Release #{release_no}) imported successfully from PDF!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/work-orders/upload-farmer-list', methods=['POST'])
@admin_required
def upload_farmer_list():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        ext = os.path.splitext(filename)[1].lower()
        if ext in ['.xls', '.xlsx']:
            from excel_parser import parse_farmer_excel
            parsed_farmers = parse_farmer_excel(file_path)
            vault_doc_type = 'Farmer Excel Draft'
        else:
            from ocr_parser import parse_farmer_pdf
            parsed_farmers = parse_farmer_pdf(file_path)
            vault_doc_type = 'Farmer PDF Draft'
        
        # Save to vault temporarily
        vault_doc = DocumentVault(
            doc_type=vault_doc_type,
            filename=filename,
            file_path=f"/static/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        # No auto-estimation of materials from HT/LT/TC values
        # Users will manually enter consumption values
        for f in parsed_farmers:
            f['materials'] = {}

            
        return jsonify({
            'success': True,
            'farmers': parsed_farmers,
            'vault_doc_id': vault_doc.id,
            'file_path': f"/static/uploads/{filename}"
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@app.route('/work-orders/save-farmer-list-ocr', methods=['POST'])
@admin_required
def save_farmer_list_ocr():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        release_order_id = data.get('release_order_id')
        farmers_data = data.get('farmers', [])
        vault_doc_id = data.get('vault_doc_id')
        
        ro = ReleaseOrder.query.get_or_404(release_order_id)
        
        from models import Farmer, FarmerMaterial
        
        # Save each farmer and their materials
        for fd in farmers_data:
            sr_number = fd.get('sr_number') or f"GEN-{datetime.utcnow().timestamp()}"
            applicant_name = fd.get('applicant_name', 'UNKNOWN')
            village = fd.get('village', 'UNKNOWN')
            
            date_str = fd.get('date')
            from ocr_parser import parse_date
            parsed_date = parse_date(date_str) if date_str else date.today()
            
            ht = Decimal(str(fd.get('ht', '0.0')))
            lt4 = Decimal(str(fd.get('lt4', '0.0')))
            lt2 = Decimal(str(fd.get('lt2', '0.0')))
            tc = int(fd.get('tc', 0))
            ex = Decimal(str(fd.get('ex', '0.0')))
            
            # Create Farmer record
            farmer = Farmer(
                release_order_id=ro.id,
                sr_number=sr_number,
                applicant_name=applicant_name,
                village=village,
                date=parsed_date,
                ht=ht,
                lt4=lt4,
                lt2=lt2,
                tc=tc,
                ex=ex,
                status='Pending',
                po_no=ro.po_no,
                release_no=ro.release_no
            )
            db.session.add(farmer)
            db.session.flush() # get farmer ID
            
            # Save Materials
            poles_data = fd.get('poles', [])
            if poles_data:
                for pole_d in poles_data:
                    pole_no = str(pole_d.get('pole_no', ''))
                    p_materials = pole_d.get('materials', {})
                    for m_name, qty_val in p_materials.items():
                        qty = Decimal(str(qty_val))
                        resolved_code = resolve_item_code_from_name(m_name)
                        m = find_material_by_code_or_name(resolved_code, m_name)
                        
                        fm = FarmerMaterial(
                            farmer_id=farmer.id,
                            pole_no=pole_no,
                            material_name=m.name if m else m_name,
                            item_code=m.item_code if m else resolved_code,
                            qty_required=qty,
                            qty_issued=0.0,
                            qty_consumed=0.0
                        )
                        db.session.add(fm)
            else:
                materials = fd.get('materials', {})
                for m_name, qty_val in materials.items():
                    qty = Decimal(str(qty_val))
                    resolved_code = resolve_item_code_from_name(m_name)
                    m = find_material_by_code_or_name(resolved_code, m_name)
                    
                    fm = FarmerMaterial(
                        farmer_id=farmer.id,
                        pole_no=None,
                        material_name=m.name if m else m_name,
                        item_code=m.item_code if m else resolved_code,
                        qty_required=qty,
                        qty_issued=0.0,
                        qty_consumed=0.0
                    )
                    db.session.add(fm)
                
        # Link document in vault if present
        if vault_doc_id:
            vault_doc = DocumentVault.query.get(vault_doc_id)
            if vault_doc:
                vault_doc.related_id = ro.id
                vault_doc.doc_type = 'Farmer Excel' # elevated/linked type
                
        db.session.commit()
        flash(f'Farmer List ({len(farmers_data)} farmers) imported and linked to Release Order #{ro.release_no}!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


# ===================== INVENTORY ROUTES =====================

@app.route('/inventory', methods=['GET', 'POST'])
@admin_required
def inventory():
    if request.method == 'POST':
        # Check if manual receipt or credit receipt is submitted
        form_type = request.form.get('form_type')
        
        if form_type == 'receipt':
            receipt_no = request.form.get('receipt_no')
            receipt_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
            
            material_name = request.form.get('material')
            qty = Decimal(request.form.get('qty', '0'))
            rate = Decimal(request.form.get('rate', '0'))
            
            # Create receipt
            receipt = MaterialReceipt(
                release_order_id=None,
                receipt_no=receipt_no,
                date=receipt_date
            )
            db.session.add(receipt)
            db.session.flush()
            
            item = MaterialReceiptItem(
                receipt_id=receipt.id,
                material_name=material_name,
                qty=qty,
                rate=rate
            )
            db.session.add(item)
            
            # Update central stock
            m = Material.query.filter_by(name=material_name).first()
            if m:
                m.received_qty += qty
            else:
                m = Material(name=material_name, unit='Nos', received_qty=qty)
                db.session.add(m)
                
            db.session.commit()
            flash('Material receipt recorded, stock increased successfully.', 'success')
            
        elif form_type == 'credit':
            cr_no = request.form.get('cr_number')
            cr_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
            material_name = request.form.get('material')
            qty = Decimal(request.form.get('qty', '0'))
            
            cr = CreditReceipt(
                cr_number=cr_no,
                date=cr_date,
                material_name=material_name,
                qty=qty
            )
            db.session.add(cr)
            
            # Credit returns unused materials: increments central warehouse stock (adjusting opening or received)
            m = Material.query.filter_by(name=material_name).first()
            if m:
                # Return increases received_qty or we track it as a positive received adjustment
                m.received_qty += qty
            db.session.commit()
            
            # Log in vault
            vault_doc = DocumentVault(
                doc_type='CR',
                filename=f"cr_{cr_no}.txt",
                file_path=f"CR Return No {cr_no}",
                related_id=cr.id
            )
            db.session.add(vault_doc)
            db.session.commit()
            
            flash('Credit receipt recorded, stock updated successfully.', 'success')
            
        return redirect(url_for('inventory'))
        
    materials = Material.query.all()
    receipts = MaterialReceipt.query.filter(MaterialReceipt.release_order_id.is_(None)).all()
    credit_receipts = CreditReceipt.query.all()
    return render_template('inventory.html', materials=materials, receipts=receipts, credit_receipts=credit_receipts, today_date=date.today().strftime('%Y-%m-%d'))

@app.route('/inventory/update-price', methods=['POST'])
@admin_required
def inventory_update_price():
    try:
        data = request.get_json()
        material_id = data.get('material_id')
        price = data.get('price', 0)
        
        m = Material.query.get(material_id)
        if m:
            m.unit_price = Decimal(str(price))
            db.session.commit()
            return jsonify({'success': True, 'message': f'Price for {m.name} updated to ₹{price}'})
        return jsonify({'success': False, 'message': 'Material not found'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/inventory/lookup-gate-pass/<mr_number>', methods=['GET'])
@admin_required
def inventory_lookup_gate_pass(mr_number):
    from ocr_parser import normalize_mr_number
    
    normalized = normalize_mr_number(mr_number)
    already_exists = MaterialReceipt.query.filter_by(receipt_no=normalized).first() is not None
    materials = Material.query.all()
    mat_list = [{'id': m.id, 'name': m.name, 'unit': m.unit, 'unit_price': float(m.unit_price)} for m in materials]
    
    return jsonify({
        'success': True,
        'mr_number': normalized,
        'items': [],
        'all_materials': mat_list,
        'already_exists': already_exists
    })


@app.route('/inventory/material-history/<path:material_name>', methods=['GET'])
@admin_required
def inventory_material_history(material_name):
    try:
        m = Material.query.filter_by(name=material_name).first()
        if not m:
            return jsonify({'success': False, 'message': 'Material not found'})
            
        # 1. Credits: Material Receipts + Credit Returns
        credits = []
        receipt_items = MaterialReceiptItem.query.join(MaterialReceipt).filter(
            MaterialReceiptItem.material_name == material_name,
            MaterialReceipt.release_order_id.is_(None)
        ).all()
        for ri in receipt_items:
            receipt = ri.receipt
            credits.append({
                'date': receipt.date.strftime('%d-%b-%Y'),
                'qty': float(ri.qty),
                'source': f"MR: {receipt.receipt_no}",
                'rate': float(ri.rate)
            })
        cr_receipts = CreditReceipt.query.filter_by(material_name=material_name).all()
        for cr in cr_receipts:
            credits.append({
                'date': cr.date.strftime('%d-%b-%Y'),
                'qty': float(cr.qty),
                'source': f"CR: {cr.cr_number}",
                'rate': 0.0
            })
            
        # 2. Debits: Farmer material issues
        debits = []
        # Import here to avoid circular imports — these models still exist in models.py
        from models import FarmerMaterial, Farmer, ReleaseOrder
        farmer_materials = FarmerMaterial.query.filter_by(material_name=material_name).all()
        for fm in farmer_materials:
            farmer = fm.farmer
            if farmer.status not in ['Material Issued', 'Started', 'Completed']:
                continue
            
            qty = float(fm.qty_issued or 0.0) + float(fm.qty_consumed or 0.0)
            if qty <= 0:
                continue
                
            rel_no = farmer.release_order.release_no if farmer.release_order else 'N/A'
            f_date = farmer.date.strftime('%d-%b-%Y') if farmer.date else "N/A"
            debits.append({
                'date': f_date,
                'qty': qty,
                'farmer': farmer.applicant_name,
                'release_no': rel_no,
                'status': farmer.status
            })
            
        # 3. Create Combined Ledger (sorted date descending)
        ledger = []
        for c in credits:
            ledger.append({
                'date': c['date'],
                'type': 'Credit (Inflow)',
                'qty': f"+{c['qty']}",
                'source': c['source'],
                'badge_class': 'bg-success'
            })
        for d in debits:
            ledger.append({
                'date': d['date'],
                'type': f"Debit ({d['status']})",
                'qty': f"-{d['qty']}",
                'source': f"Farmer: {d['farmer']} (RO: {d['release_no']})",
                'badge_class': 'bg-danger'
            })
            
        from datetime import datetime
        def get_ledger_sort_date(x):
            if x['date'] == 'N/A' or not x['date']:
                return datetime.min
            try:
                return datetime.strptime(x['date'], '%d-%b-%Y')
            except:
                return datetime.min
        ledger.sort(key=get_ledger_sort_date, reverse=True)
            
        return jsonify({
            'success': True,
            'material_name': material_name,
            'credits': credits,
            'debits': debits,
            'ledger': ledger
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@app.route('/inventory/check-mr-exists/<mr_number>', methods=['GET'])
@admin_required
def check_mr_exists(mr_number):
    exists = MaterialReceipt.query.filter_by(receipt_no=mr_number).first() is not None
    return jsonify({'exists': exists})

@app.route('/inventory/upload-gate-pass', methods=['POST'])
@admin_required
def inventory_upload_gate_pass():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Determine if file is PDF or image and parse accordingly
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            from ocr_parser import extract_text_from_pdf, parse_gate_pass_text
            extracted_text = extract_text_from_pdf(file_path)
            parsed_data = parse_gate_pass_text(extracted_text)
            doc_type = 'Gate Pass PDF'
        else:
            parsed_data = parse_gate_pass_image(file_path)
            doc_type = 'Gate Pass Photo'
        
        # Add to DocumentVault temporarily
        vault_doc = DocumentVault(
            doc_type=doc_type,
            filename=filename,
            file_path=f"/static/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        # Fetch materials to help map parsed items
        materials = Material.query.all()
        mat_list = [{'id': m.id, 'name': m.name, 'unit': m.unit, 'unit_price': float(m.unit_price)} for m in materials]
        
        mr_number = parsed_data.get('mr_number', '')
        already_exists = MaterialReceipt.query.filter_by(receipt_no=mr_number).first() is not None if mr_number else False
        
        return jsonify({
            'success': True,
            'mr_number': mr_number,
            'already_exists': already_exists,
            'requestor': parsed_data.get('requestor', ''),
            'po_no': parsed_data.get('po_no', ''),
            'items': parsed_data.get('items', []),
            'all_materials': mat_list,
            'file_path': f"/static/uploads/{filename}",
            'vault_doc_id': vault_doc.id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@app.route('/inventory/save-gate-pass', methods=['POST'])
@admin_required
def inventory_save_gate_pass():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        mr_number = data.get('mr_number') or 'GP-MANUAL'
        date_str = data.get('date')
        receipt_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
        items = data.get('items', [])
        vault_doc_id = data.get('vault_doc_id')
        
        if not items:
            return jsonify({'success': False, 'message': 'No items to save'})
            
        # Create MaterialReceipt
        receipt = MaterialReceipt(
            release_order_id=None,
            receipt_no=mr_number,
            date=receipt_date
        )
        db.session.add(receipt)
        db.session.flush() # get receipt ID
        
        for it in items:
            material_name = it.get('material_name')
            qty = Decimal(str(it.get('qty', '0')))
            rate = Decimal(str(it.get('rate', '0')))
            is_new = it.get('is_new', False)
            unit = it.get('unit', 'Nos')
            item_code = it.get('item_code')
            
            # If "Create New Material" is selected
            if is_new:
                # check if already exists
                m = Material.query.filter_by(name=material_name).first()
                if not m:
                    m = Material(name=material_name, unit=unit, received_qty=qty, unit_price=rate, item_code=item_code)
                    db.session.add(m)
                else:
                    m.received_qty += qty
                    if item_code and not m.item_code:
                        m.item_code = item_code
            else:
                m = Material.query.filter_by(name=material_name).first()
                if m:
                    m.received_qty += qty
                    # Save unit price if updated
                    if rate > 0 and m.unit_price == 0:
                        m.unit_price = rate
                    if item_code and not m.item_code:
                        m.item_code = item_code
                else:
                    m = Material(name=material_name, unit=unit, received_qty=qty, unit_price=rate, item_code=item_code)
                    db.session.add(m)
                    
            receipt_item = MaterialReceiptItem(
                receipt_id=receipt.id,
                material_name=material_name,
                qty=qty,
                rate=rate
            )
            db.session.add(receipt_item)
            
        # Link Vault document if available
        if vault_doc_id:
            vault_doc = DocumentVault.query.get(vault_doc_id)
            if vault_doc:
                vault_doc.related_id = receipt.id
                vault_doc.doc_type = 'Material Receipt' # elevate from temporary gate pass photo
                
        db.session.commit()
        flash(f'Gate Pass MR-{mr_number} imported successfully! Stock updated.', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/inventory/update-material', methods=['POST'])
@admin_required
def inventory_update_material():
    try:
        data = request.get_json()
        mat_id = data.get('material_id')
        name = data.get('name')
        item_code = data.get('item_code')
        unit = data.get('unit')
        price = data.get('price', 0)
        
        m = Material.query.get(mat_id)
        if m:
            m.name = name
            m.item_code = item_code
            m.unit = unit
            m.unit_price = Decimal(str(price))
            db.session.commit()
            return jsonify({'success': True, 'message': f'Material {name} updated successfully.'})
        return jsonify({'success': False, 'message': 'Material not found'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/inventory/save-debit', methods=['POST'])
@admin_required
def inventory_save_debit():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        farmer_name = data.get('farmer_name')
        village = data.get('village', '')
        po_no = data.get('po_no')
        release_no = data.get('release_no')
        date_str = data.get('date')
        items = data.get('items', [])
        
        if not farmer_name or not items:
            return jsonify({'success': False, 'message': 'Farmer name and items are required'})
            
        issue_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
        
        # Generate sr_number
        import uuid
        sr_number = f"SR-{uuid.uuid4().hex[:8].upper()}"
        
        # Create Farmer
        from models import Farmer, FarmerMaterial
        farmer = Farmer(
            applicant_name=farmer_name,
            village=village,
            po_no=po_no,
            release_no=release_no,
            date=issue_date,
            sr_number=sr_number,
            status='Material Issued'
        )
        db.session.add(farmer)
        db.session.flush() # get farmer ID
        
        for it in items:
            mat_name = it.get('material_name')
            qty = Decimal(str(it.get('qty', '0')))
            
            resolved_code = resolve_item_code_from_name(mat_name)
            m = find_material_by_code_or_name(resolved_code, mat_name)
            if m:
                m.issued_qty += qty
                
                fm = FarmerMaterial(
                    farmer_id=farmer.id,
                    material_name=m.name,
                    item_code=m.item_code,
                    qty_required=qty,
                    qty_issued=qty,
                    qty_consumed=0.0
                )
                db.session.add(fm)
        
        db.session.commit()
        flash(f"Debit recorded successfully for farmer {farmer_name}.", "success")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/inventory/debit/delete/<int:farmer_id>', methods=['POST'])
@admin_required
def debit_delete(farmer_id):
    from models import Farmer
    farmer = Farmer.query.get_or_404(farmer_id)
    try:
        for fm in farmer.materials:
            m = find_material_by_code_or_name(fm.item_code, fm.material_name)
            if m:
                m.issued_qty = max(0, m.issued_qty - fm.qty_issued)
        db.session.delete(farmer)
        db.session.commit()
        flash('Debit record deleted and warehouse stock adjusted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting debit record: {e}', 'danger')
    return redirect(url_for('inventory'))

@app.route('/inventory/debit-history', methods=['GET'])
@admin_required
def inventory_debit_history():
    try:
        from models import Farmer
        farmers = Farmer.query.order_by(Farmer.date.desc(), Farmer.id.desc()).all()
        data = []
        for f in farmers:
            items = []
            for fm in f.materials:
                qty = Decimal(str(fm.qty_issued or 0.0)) + Decimal(str(fm.qty_consumed or 0.0))
                if qty > 0:
                    items.append({
                        'material_name': fm.material_name,
                        'qty': float(qty)
                    })
            if items:
                wo_no = f.release_order.work_order.work_order_no if (f.release_order and f.release_order.work_order) else 'N/A'
                data.append({
                    'id': f.id,
                    'date': f.date.strftime('%d-%b-%Y') if f.date else 'N/A',
                    'farmer_name': f.applicant_name,
                    'po_no': f.display_po_no,
                    'release_no': f.display_release_no,
                    'work_order_no': wo_no,
                    'items': items
                })
        return jsonify({'success': True, 'debits': data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/inventory/credit-history', methods=['GET'])
@admin_required
def inventory_credit_history():
    try:
        receipts = MaterialReceipt.query.filter(MaterialReceipt.release_order_id.is_(None)).order_by(MaterialReceipt.date.desc(), MaterialReceipt.id.desc()).all()
        credits = []
        for r in receipts:
            items = []
            for ri in r.items:
                items.append({
                    'material_name': ri.material_name,
                    'qty': float(ri.qty),
                    'rate': float(ri.rate)
                })
            credits.append({
                'id': r.id,
                'type': 'Material Receipt',
                'receipt_no': r.receipt_no,
                'date': r.date.strftime('%d-%b-%Y'),
                'items': items
            })
        cr_receipts = CreditReceipt.query.order_by(CreditReceipt.date.desc(), CreditReceipt.id.desc()).all()
        for cr in cr_receipts:
            credits.append({
                'id': cr.id,
                'type': 'Surplus Return (CR)',
                'receipt_no': cr.cr_number,
                'date': cr.date.strftime('%d-%b-%Y'),
                'items': [{
                    'material_name': cr.material_name,
                    'qty': float(cr.qty),
                    'rate': 0.0
                }]
            })
        from datetime import datetime
        def get_credit_sort_date(x):
            if x['date'] == 'N/A' or not x['date']:
                return datetime.min
            try:
                return datetime.strptime(x['date'], '%d-%b-%Y')
            except:
                return datetime.min
        credits.sort(key=get_credit_sort_date, reverse=True)
        return jsonify({'success': True, 'credits': credits})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ===================== DELETE HANDLERS =====================

@app.route('/inventory/receipt/delete/<int:receipt_id>', methods=['POST'])
@admin_required
def receipt_delete(receipt_id):
    receipt = MaterialReceipt.query.get_or_404(receipt_id)
    try:
        if receipt.release_order_id is None:
            for item in receipt.items:
                m = Material.query.filter_by(name=item.material_name).first()
                if m:
                    m.received_qty = max(0, m.received_qty - item.qty)
        db.session.delete(receipt)
        db.session.commit()
        flash('Material Receipt deleted and warehouse stock adjusted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting Material Receipt: {e}', 'danger')
    return redirect(url_for('inventory'))

@app.route('/work-orders/release-order/delete/<int:ro_id>', methods=['POST'])
@admin_required
def delete_release_order(ro_id):
    from models import MaterialReceiptItem, Farmer, FarmerMaterial, Bill
    ro = ReleaseOrder.query.get_or_404(ro_id)
    work_order_id = ro.work_order_id
    try:
        # 1. Clean up associated DocumentVault entries
        DocumentVault.query.filter(
            (DocumentVault.related_id == ro.id) & 
            ((DocumentVault.doc_type == 'Release Order') | (DocumentVault.doc_type == 'Farmer List'))
        ).delete()
        
        # 2. Revert Central Inventory for any Material Receipt items under this Release Order
        for receipt in ro.receipts:
            for item in receipt.items:
                m = Material.query.filter_by(name=item.material_name).first()
                if m:
                    m.received_qty = max(0, m.received_qty - item.qty)
            MaterialReceiptItem.query.filter_by(receipt_id=receipt.id).delete()
            db.session.delete(receipt)
            
        # 3. Handle Farmers linked to this Release Order: revert inventory and delete
        for farmer in ro.farmers:
            for fm in farmer.materials:
                m = Material.query.filter_by(name=fm.material_name).first()
                if m:
                    m.issued_qty = max(0, m.issued_qty - fm.qty_issued)
                    m.consumed_qty = max(0, m.consumed_qty - fm.qty_consumed)
                db.session.delete(fm)
            db.session.delete(farmer)
            
        # 4. Clean up any Bills associated with this Release Order
        for bill in ro.bills:
            DocumentVault.query.filter_by(related_id=bill.id, doc_type='Bill').delete()
            db.session.delete(bill)
            
        # 5. Restore WorkOrder balance amount
        wo = ro.work_order
        if wo:
            wo.balance_amount = min(wo.contract_amount, wo.balance_amount + ro.release_amount)
            
        # 6. Delete the Release Order
        db.session.delete(ro)
        db.session.commit()
        flash('Sub-Work Order deleted successfully and inventory adjusted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting Sub-Work Order: {e}', 'danger')
        
    return redirect(url_for('work_order_details', wo_id=work_order_id))


@app.route('/inventory/credit/delete/<int:credit_id>', methods=['POST'])
@admin_required
def credit_delete(credit_id):
    cr = CreditReceipt.query.get_or_404(credit_id)
    try:
        m = Material.query.filter_by(name=cr.material_name).first()
        if m:
            m.received_qty = max(0, m.received_qty - cr.qty)
        DocumentVault.query.filter_by(related_id=cr.id, doc_type='CR').delete()
        db.session.delete(cr)
        db.session.commit()
        flash('Credit Receipt deleted and warehouse stock adjusted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting Credit Receipt: {e}', 'danger')
    return redirect(url_for('inventory'))

# ===================== MANAGER DASHBOARD & CONSUMPTION =====================

def derive_ro_status(ro):
    """Auto-derive ReleaseOrder status from all its farmers' statuses."""
    if not ro.farmers:
        return ro.status  # No farmers, keep current status
    
    statuses = set(f.status for f in ro.farmers)
    
    # All Completed -> Completed
    if statuses == {'Completed'}:
        return 'Completed'
    # All Disputed -> Disputed
    if statuses == {'Disputed'}:
        return 'Disputed'
    # If any is Started, or mix of Completed and Active/Started/Pending -> In Progress
    if 'Started' in statuses:
        return 'In Progress'
    if 'Completed' in statuses and (statuses & {'Active', 'Started', 'Pending'}):
        return 'In Progress'
    # If any is Active (and not Started) -> Active
    if 'Active' in statuses:
        return 'Active'
    # All Pending, or mix of Pending + Disputed -> Pending
    if statuses <= {'Pending', 'Disputed'}:
        return 'Pending'
    
    return 'Pending'

@app.route('/manager')
@login_required
def manager_dashboard():
    from models import WorkOrder
    work_orders = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    
    # Auto-derive each RO status from its farmers
    for wo in work_orders:
        for ro in wo.release_orders:
            derived = derive_ro_status(ro)
            if ro.status != derived:
                ro.status = derived
    db.session.commit()
    
    return render_template('manager.html', work_orders=work_orders)

@app.route('/manager/farmer-status/<int:farmer_id>', methods=['POST'])
@login_required
def manager_farmer_status(farmer_id):
    """Update a single farmer's status to Active, Disputed, or Pending."""
    from models import Farmer, FarmerMaterial, Material
    from decimal import Decimal
    
    farmer = Farmer.query.get_or_404(farmer_id)
    ro = farmer.release_order
    new_status = request.form.get('status')
    
    if new_status not in ['Active', 'Disputed', 'Pending']:
        flash("Invalid status.", "danger")
        return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
    
    old_status = farmer.status
    
    # If setting to Disputed (rejected), clear consumption values and un-debit stock
    if new_status == 'Disputed' and old_status in ['Active', 'Started']:
        for fm in farmer.materials:
            fm.qty_consumed = Decimal('0.0')
        # Re-sync warehouse consumed totals
        material_names = set(fm.material_name for fm in farmer.materials)
        for m_name in material_names:
            m = Material.query.filter_by(name=m_name).first()
            if m:
                from sqlalchemy import func
                total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                    FarmerMaterial.material_name == m_name
                ).scalar() or Decimal('0.0')
                m.consumed_qty = Decimal(str(total_consumed))
    
    farmer.status = new_status
    
    # Auto-derive the parent RO status
    ro.status = derive_ro_status(ro)
    
    db.session.commit()
    
    status_labels = {'Active': 'Activated', 'Disputed': 'Rejected (Disputed)', 'Pending': 'Reset to Pending'}
    flash(f"Farmer {farmer.applicant_name} — {status_labels.get(new_status, new_status)}.", "success")
    return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))

@app.route('/manager/update-status/<int:ro_id>', methods=['POST'])
@login_required
def manager_update_status(ro_id):
    """Bulk update: sets all farmers of the RO then auto-derives RO status."""
    from models import ReleaseOrder
    ro = ReleaseOrder.query.get_or_404(ro_id)
    new_status = request.form.get('status')
    if new_status in ['Pending', 'Active', 'Disputed']:
        for f in ro.farmers:
            f.status = new_status
        ro.status = derive_ro_status(ro)
        db.session.commit()
        flash(f"Sub-Work Order #{ro.release_no} — all farmers set to {new_status}.", "success")
        if new_status == 'Active':
            return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
    return redirect(url_for('manager_dashboard'))

def material_sort_key(name):
    """Sorts material names according to the specific sequence in UGVCL Material Account Sheet."""
    if not name:
        return 9999
    name_clean = name.lower().strip()
    
    # Custom sequence
    sequence = [
        "conducto 34mm 2wire",
        "conductor 34mm 5wire",
        "psc pole 8 mtr",
        "psc pole 10 mtr",
        "three hole parties",
        "v-x arm",
        "top fitting",
        "side clamp",
        "earthing plate/coil",
        "g.i. wire 8 no.",
        "stay wire 7/12",
        "stay clamp pair",
        "turn buckle",
        "eye bolt",
        "stay insulator",
        "anchor road",
        "c.c. block",
        "u claimp",
        "lt shackle",
        "pvc pipe",
        "bolt-2.6\"(with nut)",
        "bolt-5.0\"(with nut)",
        "bolt-7.0\"(with nut)",
        "bolt-11.0\"(with nut)"
    ]
    
    for idx, seq_name in enumerate(sequence):
        if seq_name in name_clean or name_clean in seq_name:
            return idx
            
    return len(sequence) + ord(name[0].lower())

def standardize_release_order_records(ro_id):
    """Standardizes FarmerMaterial and MaterialReceiptItem names for a specific Release Order to match standard inventory names."""
    try:
        from models import FarmerMaterial, MaterialReceiptItem, Material, Farmer, ReleaseOrder
        ro = ReleaseOrder.query.get(ro_id)
        if not ro:
            return
            
        # 1. Standardize FarmerMaterials for all farmers in this RO
        farmers = ro.farmers
        farmer_ids = [f.id for f in farmers]
        if farmer_ids:
            fms = FarmerMaterial.query.filter(FarmerMaterial.farmer_id.in_(farmer_ids)).all()
            changed_any = False
            for fm in fms:
                code = fm.item_code
                if not code:
                    code = resolve_item_code_from_name(fm.material_name)
                if code:
                    m = Material.query.filter_by(item_code=code).first()
                    if m:
                        if fm.material_name != m.name:
                            fm.material_name = m.name
                            changed_any = True
                        if fm.item_code != m.item_code:
                            fm.item_code = m.item_code
                            changed_any = True
            if changed_any:
                db.session.commit()
                
        # 2. Standardize MaterialReceiptItems for this RO's receipts
        receipt_ids = [r.id for r in ro.receipts]
        if receipt_ids:
            items = MaterialReceiptItem.query.filter(MaterialReceiptItem.receipt_id.in_(receipt_ids)).all()
            changed_any = False
            for item in items:
                code = resolve_item_code_from_name(item.material_name)
                if code:
                    m = Material.query.filter_by(item_code=code).first()
                    if m and item.material_name != m.name:
                        item.material_name = m.name
                        changed_any = True
            if changed_any:
                db.session.commit()
    except Exception as e:
        print(f"Error standardizing RO {ro_id} records: {e}")
        db.session.rollback()

def get_sub_order_context(ro_id):
    from models import ReleaseOrder, Farmer, FarmerMaterial, Material
    from decimal import Decimal
    
    # Self-heal and standardize all material names first to match central inventory by item code
    standardize_release_order_records(ro_id)
    
    ro = ReleaseOrder.query.get_or_404(ro_id)
    wo = ro.work_order
    
    derived = derive_ro_status(ro)
    if ro.status != derived:
        ro.status = derived
        db.session.commit()
    
    farmers = ro.farmers
    
    material_names = set()
    all_m = Material.query.all()
    for m in all_m:
        if m.opening_stock > 0 or m.received_qty > 0 or m.issued_qty > 0 or m.consumed_qty > 0:
            material_names.add(m.name)
            
    material_list = sorted(list(material_names), key=material_sort_key)
    
    material_units = {}
    for name in material_list:
        m = Material.query.filter_by(name=name).first()
        material_units[name] = m.unit if m else 'Nos'
        
    required_map = {}
    required_pole_map = {}
    consumption_map = {}
    farmer_poles = {}
    
    for f in farmers:
        required_map[f.id] = {}
        for m_name in material_list:
            from sqlalchemy import func
            req_sum = db.session.query(func.sum(FarmerMaterial.qty_required)).filter_by(
                farmer_id=f.id, material_name=m_name
            ).scalar() or Decimal('0.0')
            required_map[f.id][m_name] = req_sum
            
        poles_query = db.session.query(FarmerMaterial.pole_no).filter(
            FarmerMaterial.farmer_id == f.id,
            FarmerMaterial.pole_no.isnot(None)
        ).distinct().all()
        
        def pole_sort_key(p):
            try:
                num = re.search(r'\d+', p)
                return int(num.group()) if num else 9999
            except:
                return 9999
        poles = sorted(list(set([p[0] for p in poles_query if p[0]])), key=pole_sort_key)
        if not poles:
            poles = ['1']
            
        farmer_poles[f.id] = poles
        
        required_pole_map[f.id] = {}
        consumption_map[f.id] = {}
        
        for p in poles:
            required_pole_map[f.id][p] = {}
            consumption_map[f.id][p] = {}
            for m_name in material_list:
                fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=p).first()
                if fm:
                    required_pole_map[f.id][p][m_name] = fm.qty_required
                    consumption_map[f.id][p][m_name] = fm.qty_consumed
                else:
                    required_pole_map[f.id][p][m_name] = required_map[f.id][m_name] if p == poles[0] else Decimal('0.0')
                    consumption_map[f.id][p][m_name] = None

    status_counts = {}
    for f in farmers:
        status_counts[f.status] = status_counts.get(f.status, 0) + 1
        
    material_stocks = {}
    for name in material_list:
        m = Material.query.filter_by(name=name).first()
        if m:
            current_ro_consumed = Decimal('0.0')
            for farmer in farmers:
                for fm in farmer.materials:
                    if fm.material_name == name:
                        current_ro_consumed += fm.qty_consumed or Decimal('0.0')
            material_stocks[name] = float(m.current_stock + current_ro_consumed)
        else:
            material_stocks[name] = 0.0
            
    return {
        'ro': ro, 'wo': wo, 'farmers': farmers, 'materials': material_list,
        'material_units': material_units, 'required_map': required_map,
        'required_pole_map': required_pole_map, 'consumption_map': consumption_map,
        'farmer_poles': farmer_poles, 'material_stocks': material_stocks,
        'status_counts': status_counts, 'float': float, 'isinstance': isinstance, 'Decimal': Decimal
    }

@app.route('/manager/farmer/<int:farmer_id>/taping', methods=['GET'])
@login_required
def manager_get_taping(farmer_id):
    from models import Farmer, FarmerMaterial
    farmer = Farmer.query.get_or_404(farmer_id)
    fms = FarmerMaterial.query.filter_by(farmer_id=farmer_id, pole_no='EX').all()
    materials = []
    for fm in fms:
        if fm.qty_consumed and fm.qty_consumed > 0:
            materials.append({
                'material_name': fm.material_name,
                'qty_consumed': float(fm.qty_consumed)
            })
    return jsonify({
        'taping_price': float(farmer.ex or 0.0),
        'materials': materials
    })

@app.route('/manager/farmer/<int:farmer_id>/taping', methods=['POST'])
@login_required
def manager_save_taping(farmer_id):
    from models import Farmer, FarmerMaterial, Material
    from decimal import Decimal
    
    farmer = Farmer.query.get_or_404(farmer_id)
    ro = farmer.release_order
    if ro and ro.status == 'Completed':
        flash("This Sub-Work Order is finalized and locked.", "danger")
        return redirect(url_for('manager_active_farmers', ro_id=ro.id))
        
    taping_price_str = request.form.get('taping_price', '0.0').strip()
    try:
        taping_price = Decimal(taping_price_str) if taping_price_str else Decimal('0.0')
    except:
        taping_price = Decimal('0.0')
        
    farmer.ex = taping_price
    
    # 1. Clear old EX pole records for this farmer
    FarmerMaterial.query.filter_by(farmer_id=farmer_id, pole_no='EX').delete()
    
    # 2. Add new ones
    materials_data = request.form.getlist('materials[]')
    qtys_data = request.form.getlist('qtys[]')
    
    for mat_name, qty_str in zip(materials_data, qtys_data):
        if not mat_name or not qty_str:
            continue
        try:
            qty = Decimal(qty_str)
        except:
            qty = Decimal('0.0')
            
        if qty > 0:
            m = Material.query.filter_by(name=mat_name).first()
            fm = FarmerMaterial(
                farmer_id=farmer_id,
                pole_no='EX',
                material_name=mat_name,
                item_code=m.item_code if m else resolve_item_code_from_name(mat_name),
                qty_required=Decimal('0.0'),
                qty_issued=Decimal('0.0'),
                qty_consumed=qty
            )
            db.session.add(fm)
            
    # 3. Synchronize consumed quantities for central warehouse
    db.session.flush()
    all_materials = Material.query.all()
    for m in all_materials:
        if m.opening_stock > 0 or m.received_qty > 0 or m.issued_qty > 0 or m.consumed_qty > 0:
            from sqlalchemy import func, or_
            if m.item_code:
                total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                    or_(
                        FarmerMaterial.item_code == m.item_code,
                        FarmerMaterial.material_name == m.name
                    )
                ).scalar() or Decimal('0.0')
            else:
                total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                    FarmerMaterial.material_name == m.name
                ).scalar() or Decimal('0.0')
            m.consumed_qty = Decimal(str(total_consumed))
            
    db.session.commit()
    flash("Taping (EX) details updated successfully.", "success")
    return redirect(url_for('manager_active_farmers', ro_id=ro.id))

@app.route('/manager/sub-order/<int:ro_id>')
@login_required
def manager_sub_order_detail(ro_id):
    ctx = get_sub_order_context(ro_id)
    return render_template('manager_detail.html', **ctx)

@app.route('/manager/sub-order/<int:ro_id>/active-farmers')
@login_required
def manager_active_farmers(ro_id):
    ctx = get_sub_order_context(ro_id)
    return render_template('manager_active_farmers.html', **ctx)

@app.route('/manager/sub-order/<int:ro_id>/save', methods=['POST'])
@login_required
def manager_save_consumption(ro_id):
    from models import ReleaseOrder, Farmer, FarmerMaterial, Material
    from decimal import Decimal
    
    ro = ReleaseOrder.query.get_or_404(ro_id)
    if ro.status == 'Completed':
        flash("This Sub-Work Order is finalized and locked.", "danger")
        return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
        
    action = request.form.get('action') # 'draft' or 'submit'
    
    farmers = ro.farmers
    material_names = set()
    all_m = Material.query.all()
    for m in all_m:
        if m.opening_stock > 0 or m.received_qty > 0 or m.issued_qty > 0 or m.consumed_qty > 0:
            material_names.add(m.name)
            
    material_list = list(material_names)
    
    # Calculate available stock for each material including what's already consumed in this RO
    available_stocks = {}
    for m_name in material_list:
        m = Material.query.filter_by(name=m_name).first()
        if m:
            current_ro_consumed = Decimal('0.0')
            for farmer in farmers:
                for fm in farmer.materials:
                    if fm.material_name == m_name:
                        current_ro_consumed += fm.qty_consumed or Decimal('0.0')
            available_stocks[m_name] = m.current_stock + current_ro_consumed
        else:
            available_stocks[m_name] = Decimal('0.0')
    
    # 1. Parse all submitted values and calculate proposed new consumption per material
    proposed_consumption = {} # m_name -> Decimal
    for m_name in material_list:
        proposed_consumption[m_name] = Decimal('0.0')

    for f in farmers:
        if f.status not in ['Active', 'Started']:
            continue
            
        pole_keys = [k for k in request.form.keys() if k.startswith(f"pole_name_{f.id}_")]
        submitted_poles = {}
        for pk in pole_keys:
            old_p = pk.replace(f"pole_name_{f.id}_", "")
            new_p = request.form.get(pk, '').strip()
            if new_p:
                submitted_poles[old_p] = new_p
                
        if not submitted_poles:
            submitted_poles['1'] = '1'
            for m_name in material_list:
                input_key_old = f"consumed_{f.id}_{m_name}"
                input_key_new = f"consumed_{f.id}_1_{m_name}"
                raw_val = request.form.get(input_key_old)
                if raw_val is None:
                    raw_val = request.form.get(input_key_new, '')
                raw_val = raw_val.strip() if raw_val else ''
                val = Decimal(raw_val) if raw_val else Decimal('0.0')
                proposed_consumption[m_name] += val
        else:
            for old_p, new_p in submitted_poles.items():
                for m_name in material_list:
                    input_key = f"consumed_{f.id}_{old_p}_{m_name}"
                    raw_val = request.form.get(input_key, '').strip()
                    val = Decimal(raw_val) if raw_val else Decimal('0.0')
                    proposed_consumption[m_name] += val

    # 2. Validate proposed consumption against available stock
    for m_name, proposed_val in proposed_consumption.items():
        if proposed_val > 0:
            m = Material.query.filter_by(name=m_name).first()
            if not m:
                flash(f"Material '{m_name}' does not exist in inventory.", "danger")
                return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
            
            available_stock = available_stocks.get(m_name, Decimal('0.0'))
            
            if proposed_val > available_stock:
                flash(f"Error: Insufficient stock for '{m_name}'. Available in warehouse: {float(available_stock)} {m.unit}, Requested: {float(proposed_val)} {m.unit}.", "danger")
                return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
                
    # Save consumption values — only for Active/Started farmers (skip Disputed/Pending)
    for f in farmers:
        if f.status not in ['Active', 'Started']:
            continue  # Skip disputed/pending farmers
            
        # 1. Retrieve all submitted pole numbers and names
        # Format of pole name inputs in HTML: pole_name_{f.id}_{old_pole_no}
        pole_keys = [k for k in request.form.keys() if k.startswith(f"pole_name_{f.id}_")]
        
        submitted_poles = {} # old_pole_no -> new_pole_no
        for pk in pole_keys:
            old_p = pk.replace(f"pole_name_{f.id}_", "")
            new_p = request.form.get(pk, '').strip()
            if new_p:
                submitted_poles[old_p] = new_p
                
        if not submitted_poles:
            # Fallback for old style (test context or single pole with no name input)
            # We assume a single default pole named '1'
            submitted_poles['1'] = '1'
            for m_name in material_list:
                input_key_old = f"consumed_{f.id}_{m_name}"
                input_key_new = f"consumed_{f.id}_1_{m_name}"
                
                raw_val = request.form.get(input_key_old)
                if raw_val is None:
                    raw_val = request.form.get(input_key_new, '')
                    
                raw_val = raw_val.strip() if raw_val else ''
                val = Decimal(raw_val) if raw_val else Decimal('0.0')
                
                fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no='1').first()
                if not fm:
                    fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=None).first()
                    
                if fm:
                    fm.pole_no = '1'
                    fm.qty_consumed = val
                else:
                    m_obj = Material.query.filter_by(name=m_name).first()
                    fm = FarmerMaterial(
                        farmer_id=f.id,
                        pole_no='1',
                        material_name=m_name,
                        item_code=m_obj.item_code if m_obj else resolve_item_code_from_name(m_name),
                        qty_required=Decimal('0.0'),
                        qty_issued=Decimal('0.0'),
                        qty_consumed=val
                    )
                    db.session.add(fm)
        else:
            # 2. Update material consumption values for each submitted pole
            for old_p, new_p in submitted_poles.items():
                for m_name in material_list:
                    input_key = f"consumed_{f.id}_{old_p}_{m_name}"
                    raw_val = request.form.get(input_key, '').strip()
                    val = Decimal(raw_val) if raw_val else Decimal('0.0')
                    
                    # Check if there is an existing record under old pole name
                    fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=old_p).first()
                    if fm:
                        fm.pole_no = new_p
                        fm.qty_consumed = val
                    else:
                        # Check if exists under new pole name
                        fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=new_p).first()
                        if fm:
                            fm.qty_consumed = val
                        else:
                            m_obj = Material.query.filter_by(name=m_name).first()
                            fm = FarmerMaterial(
                                farmer_id=f.id,
                                pole_no=new_p,
                                material_name=m_name,
                                item_code=m_obj.item_code if m_obj else resolve_item_code_from_name(m_name),
                                qty_required=Decimal('0.0'),
                                qty_issued=Decimal('0.0'),
                                qty_consumed=val
                            )
                            db.session.add(fm)
                            
            # 3. Handle deleted poles by permanently removing their DB records
            all_db_poles = db.session.query(FarmerMaterial.pole_no).filter(
                FarmerMaterial.farmer_id == f.id,
                FarmerMaterial.pole_no.isnot(None)
            ).distinct().all()
            all_db_poles = [p[0] for p in all_db_poles if p[0]]
            
            new_pole_names = set(submitted_poles.values())
            for db_p in all_db_poles:
                if db_p not in new_pole_names:
                    fms_to_delete = FarmerMaterial.query.filter_by(farmer_id=f.id, pole_no=db_p).all()
                    for fm in fms_to_delete:
                        db.session.delete(fm)
                
    # Update farmer statuses — only Active/Started farmers
    if action == 'submit':
        for f in farmers:
            if f.status in ['Active', 'Started']:
                f.status = 'Completed'
        flash(f"Sub-Work Order #{ro.release_no} consumption sheet finalized and submitted.", "success")
    else:
        for f in farmers:
            if f.status == 'Active':
                f.status = 'Started'
            # Already-Started farmers stay Started
        flash(f"Sub-Work Order #{ro.release_no} consumption draft saved.", "success")
    
    # Auto-derive the RO status from farmer statuses
    ro.status = derive_ro_status(ro)
        
    db.session.flush()
    
    # Synchronize central warehouse consumed quantities
    for m_name in material_list:
        resolved_code = resolve_item_code_from_name(m_name)
        m = find_material_by_code_or_name(resolved_code, m_name)
        if m:
            from sqlalchemy import func, or_
            if m.item_code:
                total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                    or_(
                        FarmerMaterial.item_code == m.item_code,
                        FarmerMaterial.material_name == m.name
                    )
                ).scalar() or Decimal('0.0')
            else:
                total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                    FarmerMaterial.material_name == m.name
                ).scalar() or Decimal('0.0')
            m.consumed_qty = Decimal(str(total_consumed))
            
    db.session.commit()
    
    if action == 'submit':
        return redirect(url_for('manager_dashboard'))
    if request.referrer and 'active-farmers' in request.referrer:
        return redirect(url_for('manager_active_farmers', ro_id=ro.id))
    return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))

@app.route('/manager/sub-order/<int:ro_id>/download-excel')
@login_required
def manager_download_excel(ro_id):
    from models import ReleaseOrder, Farmer
    from excel_generator import generate_release_excel
    from flask import send_file
    
    ro = ReleaseOrder.query.get_or_404(ro_id)
    
    # Check if there is any pending farmer
    has_pending = Farmer.query.filter_by(release_order_id=ro.id, status='Pending').first() is not None
    if has_pending:
        flash("Cannot generate Excel spreadsheet when there are pending farmers. Please activate or reject all farmers first.", "warning")
        return redirect(url_for('manager_sub_order_detail', ro_id=ro.id))
        
    excel_stream = generate_release_excel(ro)
    filename = f"Release_{ro.release_no}_Account.xls"
    
    return send_file(
        excel_stream,
        mimetype="application/vnd.ms-excel",
        as_attachment=True,
        download_name=filename
    )

@app.route('/offline')
def offline():
    return render_template('offline.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# ===================== INITIALIZATION =====================

is_testing_init = 'pytest' in sys.modules or 'unittest' in sys.modules or app.config.get('TESTING')

if not is_testing_init:
    with app.app_context():
        db.create_all()
        migrate_database()
        seed_users()
        seed_materials()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

