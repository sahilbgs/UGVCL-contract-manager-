import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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

# Load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ugvcl-secret-key-12948194')

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
    ("PSC Pole 8 MTR", "Nos"),
    ("PSC Pole 10 MTR", "Nos"),
    ("Conducto 34mm 2wire", "Mtr"),
    ("Conductor 34mm  4wire", "Mtr"),
    ("Conductor 55 mm 3wire", "Mtr"),
    ("Transformer 10 KVA", "Nos"),
    ("Transformer 25 KVA", "Nos"),
    ("Transformer 63 KVA", "Nos"),
    ("Three Hole Parties", "Nos"),
    ("V-x arm", "Nos"),
    ("Top Fitting", "Nos"),
    ("Side Clamp", "Nos"),
    ("11kv Comp Pin Insulator", "Nos"),
    ("11kv Pin Insulator", "Nos"),
    ("11kv G.I. Pin", "Nos"),
    ("11kv Shackle Insulator", "Nos"),
    ("11kv Shackle H/W", "Set."),
    ("Earthing Plate/Coil", "Nos"),
    ("G.I. Wire 8 No.", "Kg"),
    ("Stay Wire 7/12", "Kg"),
    ("Stay Clamp Pair", "Pair"),
    ("Turn Buckle", "Nos"),
    ("Eye Bolt", "Nos"),
    ("Stay Insulator", "Nos"),
    ("Anchor Road", "Nos"),
    ("C.C. Block", "Nos"),
    ("Angle 9' Fut(65*65*6)", "Fut"),
    ("Angle 9' Fut(50*50*6)", "Fut"),
    ("Angle 4' Fut", "Fut"),
    ("Angle 2'.6'' Fut", "Fut"),
    ("11kv D.O Angle / Fuse", "Nos"),
    ("U CLAIMP", "Nos"),
    ("LT SHACKLE", "Nos"),
    ("PVC PIPE", "Nos"),
    ("L.A ", "Nos"),
    ("MS Chanal-6 fut", "Nos"),
    ("Bolt-2.6\"(with nut)", "Nos"),
    ("Bolt-5.0\"(with nut)", "Nos"),
    ("Bolt-7.0\"(with nut)", "Nos"),
    ("Bolt-11.0\"(with nut)", "Nos")
]

def seed_materials():
    """Seeds typical material items into central inventory database."""
    try:
        for name, unit in COMMON_MATERIALS:
            m = Material.query.filter_by(name=name).first()
            if not m:
                # Add default material with 0.0 opening stock so actual stock represents user additions
                new_m = Material(name=name, unit=unit, opening_stock=0.0)
                db.session.add(new_m)
        db.session.commit()
    except Exception as e:
        print(f"Error seeding materials: {e}")
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

        # Check users table for role
        columns = [c['name'] for c in inspector.get_columns('users')]
        if 'role' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'manager'"))

        # Check farmer_materials table for pole_no
        columns = [c['name'] for c in inspector.get_columns('farmer_materials')]
        if 'pole_no' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE farmer_materials ADD COLUMN pole_no VARCHAR(50)"))
    except Exception as e:
        print(f"Migration error: {e}")


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

@app.route('/work-orders/delete/<int:wo_id>', methods=['GET', 'POST'])
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
                
                existing_receipt = MaterialReceipt.query.filter_by(receipt_no=receipt_no).first()
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
                        
                        if qty > 0:
                            m = Material.query.filter_by(name=m_name).first()
                            if not m:
                                unit = 'Nos'
                                if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                                    unit = 'Mtr'
                                elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                                    unit = 'Kg'
                                m = Material(name=m_name, unit=unit, opening_stock=0.0)
                                db.session.add(m)
                                db.session.flush()
                            
                            # Sub-work order materials list is NOT a material receipt, do not increment received_qty
                            
                            item = MaterialReceiptItem(
                                receipt_id=receipt.id,
                                material_name=m_name,
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
                        status='Pending',
                        po_no=ro.po_no,
                        release_no=ro.release_no
                    )
                    db.session.add(farmer)
                    db.session.flush()
                    
                    # Compute materials
                    materials = fd.get('materials', {})
                    if not materials:
                        ht_f = float(ht)
                        lt4_f = float(lt4)
                        lt2_f = float(lt2)
                        if lt2_f > 0:
                            materials['Conducto 34mm 2wire'] = lt2_f * 1000.0
                            materials['PSC Pole 8 MTR'] = max(1.0, float(int(lt2_f * 1000.0 / 40.0)))
                        if lt4_f > 0:
                            materials['Conductor 34mm  4wire'] = lt4_f * 1000.0
                            materials['PSC Pole 8 MTR'] = materials.get('PSC Pole 8 MTR', 0.0) + max(1.0, float(int(lt4_f * 1000.0 / 40.0)))
                        if ht_f > 0:
                            materials['Conductor 55 mm 3wire'] = ht_f * 1000.0
                            materials['PSC Pole 10 MTR'] = max(1.0, float(int(ht_f * 1000.0 / 50.0)))
                        if tc > 0:
                            if tc == 10: materials['Transformer 10 KVA'] = 1
                            elif tc == 16: materials['Transformer 16 KVA'] = 1
                            elif tc == 25: materials['Transformer 25 KVA'] = 1
                            elif tc == 63: materials['Transformer 63 KVA'] = 1
                            else: materials['Transformer 25 KVA'] = 1
                            materials['PSC Pole 10 MTR'] = materials.get('PSC Pole 10 MTR', 0.0) + 2
                    
                    for m_name, qty_val in materials.items():
                        qty = Decimal(str(qty_val))
                        m = Material.query.filter_by(name=m_name).first()
                        if not m:
                            unit = 'Nos'
                            if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                                unit = 'Mtr'
                            elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                                unit = 'Kg'
                            m = Material(name=m_name, unit=unit, opening_stock=0.0)
                            db.session.add(m)
                            db.session.flush()
                            
                        fm = FarmerMaterial(
                            farmer_id=farmer.id,
                            material_name=m_name,
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
            
            existing_receipt = MaterialReceipt.query.filter_by(receipt_no=receipt_no).first()
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
                    
                    if qty > 0:
                        m = Material.query.filter_by(name=m_name).first()
                        if not m:
                            unit = 'Nos'
                            if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                                unit = 'Mtr'
                            elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                                unit = 'Kg'
                            m = Material(name=m_name, unit=unit, opening_stock=0.0)
                            db.session.add(m)
                            db.session.flush()
                        
                        # Sub-work order materials list is NOT a material receipt, do not increment received_qty
                        
                        item = MaterialReceiptItem(
                            receipt_id=receipt.id,
                            material_name=m_name,
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
                    status='Pending',
                    po_no=ro.po_no,
                    release_no=ro.release_no
                )
                db.session.add(farmer)
                db.session.flush()
                
                # Fetch materials map
                materials = fd.get('materials', {})
                if not materials:
                    # Compute materials if empty
                    ht_f = float(ht)
                    lt4_f = float(lt4)
                    lt2_f = float(lt2)
                    if lt2_f > 0:
                        materials['Conducto 34mm 2wire'] = lt2_f * 1000.0
                        materials['PSC Pole 8 MTR'] = max(1.0, float(int(lt2_f * 1000.0 / 40.0)))
                    if lt4_f > 0:
                        materials['Conductor 34mm  4wire'] = lt4_f * 1000.0
                        materials['PSC Pole 8 MTR'] = materials.get('PSC Pole 8 MTR', 0.0) + max(1.0, float(int(lt4_f * 1000.0 / 40.0)))
                    if ht_f > 0:
                        materials['Conductor 55 mm 3wire'] = ht_f * 1000.0
                        materials['PSC Pole 10 MTR'] = max(1.0, float(int(ht_f * 1000.0 / 50.0)))
                    if tc > 0:
                        if tc == 10: materials['Transformer 10 KVA'] = 1
                        elif tc == 16: materials['Transformer 16 KVA'] = 1
                        elif tc == 25: materials['Transformer 25 KVA'] = 1
                        elif tc == 63: materials['Transformer 63 KVA'] = 1
                        else: materials['Transformer 25 KVA'] = 1
                        materials['PSC Pole 10 MTR'] = materials.get('PSC Pole 10 MTR', 0.0) + 2
                
                for m_name, qty_val in materials.items():
                    qty = Decimal(str(qty_val))
                    m = Material.query.filter_by(name=m_name).first()
                    if not m:
                        unit = 'Nos'
                        if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                            unit = 'Mtr'
                        elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                            unit = 'Kg'
                        m = Material(name=m_name, unit=unit, opening_stock=0.0)
                        db.session.add(m)
                        db.session.flush()
                        
                    fm = FarmerMaterial(
                        farmer_id=farmer.id,
                        material_name=m_name,
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
        
        # Format/compute default materials for each farmer based on line dimensions
        for f in parsed_farmers:
            ht = float(f.get('ht', 0.0))
            lt4 = float(f.get('lt4', 0.0))
            lt2 = float(f.get('lt2', 0.0))
            tc = int(f.get('tc', 0))
            
            materials = {}
            if lt2 > 0:
                materials['Conducto 34mm 2wire'] = lt2 * 1000.0
                materials['PSC Pole 8 MTR'] = max(1, int(lt2 * 1000.0 / 40.0))
            if lt4 > 0:
                materials['Conductor 34mm  4wire'] = lt4 * 1000.0
                materials['PSC Pole 8 MTR'] = materials.get('PSC Pole 8 MTR', 0.0) + max(1, int(lt4 * 1000.0 / 40.0))
            if ht > 0:
                materials['Conductor 55 mm 3wire'] = ht * 1000.0
                materials['PSC Pole 10 MTR'] = max(1, int(ht * 1000.0 / 50.0))
            if tc > 0:
                # Map KVA to standard transformer names
                if tc == 10:
                    materials['Transformer 10 KVA'] = 1
                elif tc == 16:
                    materials['Transformer 16 KVA'] = 1
                elif tc == 25:
                    materials['Transformer 25 KVA'] = 1
                elif tc == 63:
                    materials['Transformer 63 KVA'] = 1
                else:
                    materials['Transformer 25 KVA'] = 1
                    
                materials['PSC Pole 10 MTR'] = materials.get('PSC Pole 10 MTR', 0.0) + 2
                
            f['materials'] = materials
            
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
                        m = Material.query.filter_by(name=m_name).first()
                        if not m:
                            unit = 'Nos'
                            if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                                unit = 'Mtr'
                            elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                                unit = 'Kg'
                            m = Material(name=m_name, unit=unit, opening_stock=0.0)
                            db.session.add(m)
                            db.session.flush()
                        
                        fm = FarmerMaterial(
                            farmer_id=farmer.id,
                            pole_no=pole_no,
                            material_name=m_name,
                            qty_required=qty,
                            qty_issued=0.0,
                            qty_consumed=0.0
                        )
                        db.session.add(fm)
            else:
                materials = fd.get('materials', {})
                for m_name, qty_val in materials.items():
                    qty = Decimal(str(qty_val))
                    m = Material.query.filter_by(name=m_name).first()
                    if not m:
                        unit = 'Nos'
                        if 'wire' in m_name.lower() or 'conductor' in m_name.lower():
                            unit = 'Mtr'
                        elif 'wire' in m_name.lower() or 'wire' in m_name.lower():
                            unit = 'Kg'
                        m = Material(name=m_name, unit=unit, opening_stock=0.0)
                        db.session.add(m)
                        db.session.flush()
                    
                    fm = FarmerMaterial(
                        farmer_id=farmer.id,
                        pole_no=None,
                        material_name=m_name,
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
    from ocr_parser import PRE_VERIFIED_GATE_PASSES, normalize_mr_number
    import copy
    
    normalized = normalize_mr_number(mr_number)
    already_exists = MaterialReceipt.query.filter_by(receipt_no=normalized).first() is not None
    
    if normalized in PRE_VERIFIED_GATE_PASSES:
        data = copy.deepcopy(PRE_VERIFIED_GATE_PASSES[normalized])
        # Fetch materials for mapping dropdown
        materials = Material.query.all()
        mat_list = [{'id': m.id, 'name': m.name, 'unit': m.unit, 'unit_price': float(m.unit_price)} for m in materials]
        data['all_materials'] = mat_list
        data['success'] = True
        data['already_exists'] = already_exists
        return jsonify(data)
    
    return jsonify({'success': False, 'message': f'No pre-verified gate pass found for MR #{mr_number}', 'already_exists': already_exists})

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
            
            m = Material.query.filter_by(name=mat_name).first()
            if m:
                m.issued_qty += qty
                
                fm = FarmerMaterial(
                    farmer_id=farmer.id,
                    material_name=mat_name,
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

@app.route('/inventory/debit/delete/<int:farmer_id>')
@admin_required
def debit_delete(farmer_id):
    from models import Farmer
    farmer = Farmer.query.get_or_404(farmer_id)
    try:
        for fm in farmer.materials:
            m = Material.query.filter_by(name=fm.material_name).first()
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

@app.route('/inventory/receipt/delete/<int:receipt_id>')
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

@app.route('/inventory/credit/delete/<int:credit_id>')
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

@app.route('/manager/sub-order/<int:ro_id>')
@login_required
def manager_sub_order_detail(ro_id):
    from models import ReleaseOrder, Farmer, FarmerMaterial, Material
    from decimal import Decimal
    
    ro = ReleaseOrder.query.get_or_404(ro_id)
    wo = ro.work_order
    
    # Auto-derive RO status
    derived = derive_ro_status(ro)
    if ro.status != derived:
        ro.status = derived
        db.session.commit()
    
    # 1. Collect all farmers for this RO
    farmers = ro.farmers
    
    # 2. Extract union of all materials associated with this RO
    material_names = set()
    for receipt in ro.receipts:
        for item in receipt.items:
            material_names.add(item.material_name)
    for f in farmers:
        for fm in f.materials:
            material_names.add(fm.material_name)
            
    material_list = sorted(list(material_names))
    
    # Get units for all materials
    material_units = {}
    for name in material_list:
        m = Material.query.filter_by(name=name).first()
        material_units[name] = m.unit if m else 'Nos'
        
    # 3. Create required and consumption maps per farmer and per pole
    required_map = {} # required_map[farmer_id][material_name] -> total required
    required_pole_map = {} # required_pole_map[farmer_id][pole_no][material_name] -> quantity required
    consumption_map = {} # consumption_map[farmer_id][pole_no][material_name] -> quantity consumed
    farmer_poles = {} # farmer_poles[farmer_id] -> list of pole numbers
    
    for f in farmers:
        # Load total required quantities (regardless of pole_no)
        required_map[f.id] = {}
        for m_name in material_list:
            from sqlalchemy import func
            req_sum = db.session.query(func.sum(FarmerMaterial.qty_required)).filter_by(
                farmer_id=f.id, material_name=m_name
            ).scalar() or Decimal('0.0')
            required_map[f.id][m_name] = req_sum
            
        # Get list of unique poles for this farmer
        poles_query = db.session.query(FarmerMaterial.pole_no).filter(
            FarmerMaterial.farmer_id == f.id,
            FarmerMaterial.pole_no.isnot(None)
        ).distinct().all()
        
        # Custom sorting logic for pole numbers (e.g. 1, 2, 10...)
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
                    # Fallback to aggregated requirement on the first pole
                    required_pole_map[f.id][p][m_name] = required_map[f.id][m_name] if p == poles[0] else Decimal('0.0')
                    consumption_map[f.id][p][m_name] = None

    # Farmer status counts for summary
    status_counts = {}
    for f in farmers:
        status_counts[f.status] = status_counts.get(f.status, 0) + 1
                
    return render_template(
        'manager_detail.html',
        ro=ro,
        wo=wo,
        farmers=farmers,
        materials=material_list,
        material_units=material_units,
        required_map=required_map,
        required_pole_map=required_pole_map,
        consumption_map=consumption_map,
        farmer_poles=farmer_poles,
        status_counts=status_counts,
        float=float,
        isinstance=isinstance,
        Decimal=Decimal
    )

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
    
    # Extract unique materials for this RO
    farmers = ro.farmers
    material_names = set()
    for receipt in ro.receipts:
        for item in receipt.items:
            material_names.add(item.material_name)
    for f in farmers:
        for fm in f.materials:
            material_names.add(fm.material_name)
            
    material_list = list(material_names)
    
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
                    fm = FarmerMaterial(
                        farmer_id=f.id,
                        pole_no='1',
                        material_name=m_name,
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
                            fm = FarmerMaterial(
                                farmer_id=f.id,
                                pole_no=new_p,
                                material_name=m_name,
                                qty_required=Decimal('0.0'),
                                qty_issued=Decimal('0.0'),
                                qty_consumed=val
                            )
                            db.session.add(fm)
                            
            # 3. Handle deleted poles by setting their consumed quantities to 0
            all_db_poles = db.session.query(FarmerMaterial.pole_no).filter(
                FarmerMaterial.farmer_id == f.id,
                FarmerMaterial.pole_no.isnot(None)
            ).distinct().all()
            all_db_poles = [p[0] for p in all_db_poles if p[0]]
            
            new_pole_names = set(submitted_poles.values())
            for db_p in all_db_poles:
                if db_p not in new_pole_names:
                    fms_to_clear = FarmerMaterial.query.filter_by(farmer_id=f.id, pole_no=db_p).all()
                    for fm in fms_to_clear:
                        fm.qty_consumed = Decimal('0.0')
                        if fm.qty_required == Decimal('0.0'):
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
        m = Material.query.filter_by(name=m_name).first()
        if m:
            from sqlalchemy import func
            total_consumed = db.session.query(func.sum(FarmerMaterial.qty_consumed)).filter(
                FarmerMaterial.material_name == m_name
            ).scalar() or Decimal('0.0')
            m.consumed_qty = Decimal(str(total_consumed))
            
    db.session.commit()
    
    if action == 'submit':
        return redirect(url_for('manager_dashboard'))
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
