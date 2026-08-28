import os
import uuid
from decimal import Decimal
from datetime import datetime, date
from flask import request, render_template, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import WorkOrder, ReleaseOrder, MaterialReceipt, MaterialReceiptItem, Farmer, FarmerMaterial, DocumentVault
from app.utils.decorators import admin_required
from app.utils.helpers import resolve_item_code_from_name, find_material_by_code_or_name
from app.work_orders import work_orders

def recalculate_wo_balance(wo):
    """Declaratively recalculates and sets work order balance amount."""
    if not wo or not wo.id:
        return
    from sqlalchemy import func
    total_released = db.session.query(func.sum(ReleaseOrder.release_amount)).filter(
        ReleaseOrder.work_order_id == wo.id
    ).scalar() or Decimal('0.00')
    wo.balance_amount = max(Decimal('0.00'), wo.contract_amount - Decimal(str(total_released)))



@work_orders.route('/', methods=['GET', 'POST'], strict_slashes=False)
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
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(file_path)
            pdf_path = f"/uploads/{filename}"
            
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
            db.session.flush()
            
        try:
            db.session.commit()
            if pdf_path and 'vault_doc' in locals() and vault_doc:
                vault_doc.related_id = wo.id
                db.session.commit()
            flash(f'Work Order {work_order_no} created successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating Work Order: {str(e)}', 'danger')
            
        return redirect(url_for('work_orders.work_orders_list'))
        
    work_orders_all = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    
    # Calculate aggregate stats
    total_contract_amount = sum(wo.contract_amount for wo in work_orders_all)
    total_balance_amount = sum(wo.balance_amount for wo in work_orders_all)
    
    return render_template('work_orders/list.html', 
                           work_orders=work_orders_all, 
                           total_contract_amount=total_contract_amount, 
                           total_balance_amount=total_balance_amount)

@work_orders.route('/upload', methods=['POST'])
@admin_required
def work_orders_upload():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        from app.services.ocr_parser import parse_work_order_pdf
        parsed_data = parse_work_order_pdf(file_path)
        
        # Save to DocumentVault as temporary/unlinked
        vault_doc = DocumentVault(
            doc_type='Work Order PDF',
            filename=filename,
            file_path=f"/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        parsed_data['success'] = True
        parsed_data['vault_doc_id'] = vault_doc.id
        parsed_data['file_path'] = f"/uploads/{filename}"
        
        # Convert date to string format for javascript input[type="date"]
        if parsed_data.get('start_date'):
            parsed_data['start_date'] = parsed_data['start_date'].strftime('%Y-%m-%d')
        if parsed_data.get('end_date'):
            parsed_data['end_date'] = parsed_data['end_date'].strftime('%Y-%m-%d')
            
        return jsonify(parsed_data)
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@work_orders.route('/save-ocr', methods=['POST'])
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

@work_orders.route('/details/<int:wo_id>', methods=['GET'])
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

@work_orders.route('/<int:wo_id>', methods=['GET'])
@admin_required
def work_order_view(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        return render_template('work_orders/details.html', wo=wo)
    except Exception as e:
        flash(f"Error loading Work Order: {str(e)}", "danger")
        return redirect(url_for('work_orders.work_orders_list'))

@work_orders.route('/delete/<int:wo_id>', methods=['POST'])
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
    return redirect(url_for('work_orders.work_orders_list'))

@work_orders.route('/add-release-order', methods=['POST'])
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
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        pdf_file.save(file_path)
        pdf_path = f"/uploads/{filename}"
        
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
    db.session.flush()
    
    # Recalculate parent Work Order balance
    recalculate_wo_balance(wo)

    
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
            from app.services.ocr_parser import parse_release_order_pdf
            parsed_data = parse_release_order_pdf(file_path)
            
            # Save associated materials list (Page 2) if present
            materials_data = parsed_data.get('materials', [])
            if materials_data:
                receipt_no = parsed_data.get('receipt_no') or f"MR-RO-{release_no}"
                from app.services.ocr_parser import normalize_mr_number
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
                for idx, fd in enumerate(farmers_data):
                    sr_number = fd.get('sr_number') or f"GEN-{uuid.uuid4().hex[:8].upper()}"
                    applicant_name = fd.get('applicant_name', 'UNKNOWN')
                    village = fd.get('village', 'UNKNOWN')
                    
                    f_date_str = fd.get('date')
                    from app.services.ocr_parser import parse_date
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
        
    return redirect(url_for('work_orders.work_order_view', wo_id=wo.id))

@work_orders.route('/upload-release-order', methods=['POST'])
@admin_required
def upload_release_order():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        from app.services.ocr_parser import parse_release_order_pdf
        parsed_data = parse_release_order_pdf(file_path)
        
        # Save to vault temporarily
        vault_doc = DocumentVault(
            doc_type='Release Order PDF',
            filename=filename,
            file_path=f"/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        parsed_data['success'] = True
        parsed_data['vault_doc_id'] = vault_doc.id
        parsed_data['file_path'] = f"/uploads/{filename}"
        
        if parsed_data.get('release_date'):
            parsed_data['release_date'] = parsed_data['release_date'].strftime('%Y-%m-%d')
            
        return jsonify(parsed_data)
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@work_orders.route('/save-release-order-ocr', methods=['POST'])
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
        db.session.flush() # get ID
        
        # Recalculate parent Work Order balance
        recalculate_wo_balance(wo)

        
        # Save associated materials list (Page 2) if present
        materials_data = data.get('materials', [])
        if materials_data:
            receipt_no = data.get('receipt_no') or f"MR-RO-{release_no}"
            from app.services.ocr_parser import normalize_mr_number
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
            for idx, fd in enumerate(farmers_data):
                sr_number = fd.get('sr_number') or f"GEN-{uuid.uuid4().hex[:8].upper()}"
                applicant_name = fd.get('applicant_name', 'UNKNOWN')
                village = fd.get('village', 'UNKNOWN')
                
                f_date_str = fd.get('date')
                from app.services.ocr_parser import parse_date
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

@work_orders.route('/upload-farmer-list', methods=['POST'])
@admin_required
def upload_farmer_list():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        ext = os.path.splitext(filename)[1].lower()
        if ext in ['.xls', '.xlsx']:
            from app.services.excel_parser import parse_farmer_excel
            parsed_farmers = parse_farmer_excel(file_path)
            vault_doc_type = 'Farmer Excel Draft'
        else:
            from app.services.ocr_parser import parse_farmer_pdf
            parsed_farmers = parse_farmer_pdf(file_path)
            vault_doc_type = 'Farmer PDF Draft'
        
        # Save to vault temporarily
        vault_doc = DocumentVault(
            doc_type=vault_doc_type,
            filename=filename,
            file_path=f"/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
        for f in parsed_farmers:
            f['materials'] = {}
            
        return jsonify({
            'success': True,
            'farmers': parsed_farmers,
            'vault_doc_id': vault_doc.id,
            'file_path': f"/uploads/{filename}"
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@work_orders.route('/save-farmer-list-ocr', methods=['POST'])
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
        
        # Save each farmer and their materials
        for idx, fd in enumerate(farmers_data):
            sr_number = fd.get('sr_number') or f"GEN-{uuid.uuid4().hex[:8].upper()}"
            applicant_name = fd.get('applicant_name', 'UNKNOWN')
            village = fd.get('village', 'UNKNOWN')
            
            date_str = fd.get('date')
            from app.services.ocr_parser import parse_date
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
                vault_doc.doc_type = 'Farmer Excel'
                
        db.session.commit()
        flash(f'Farmer List ({len(farmers_data)} farmers) imported and linked to Release Order #{ro.release_no}!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@work_orders.route('/release-order/delete/<int:ro_id>', methods=['POST'])
@admin_required
def delete_release_order(ro_id):
    ro = ReleaseOrder.query.get_or_404(ro_id)
    work_order_id = ro.work_order_id
    try:
        # 1. Clean up associated DocumentVault entries
        DocumentVault.query.filter(
            (DocumentVault.related_id == ro.id) & 
            ((DocumentVault.doc_type == 'Release Order') | (DocumentVault.doc_type == 'Farmer List'))
        ).delete()
        
        # 2. Clean up Material Receipt items under this Release Order (without decrementing received_qty since RO items were not added to central stock)
        for receipt in ro.receipts:
            MaterialReceiptItem.query.filter_by(receipt_id=receipt.id).delete()
            db.session.delete(receipt)
            
        # 3. Handle Farmers linked to this Release Order: revert inventory and delete
        for farmer in ro.farmers:
            for fm in farmer.materials:
                m = Material.query.filter_by(name=fm.material_name).first()
                if m:
                    m.issued_qty = max(0, m.issued_qty - (fm.qty_issued or 0))
                    m.consumed_qty = max(0, m.consumed_qty - (fm.qty_consumed or 0))
                db.session.delete(fm)
            db.session.delete(farmer)
            
        # 4. Clean up any Bills associated with this Release Order
        for bill in ro.bills:
            DocumentVault.query.filter_by(related_id=bill.id, doc_type='Bill').delete()
            db.session.delete(bill)
            
        # 5. Delete the Release Order and recalculate WorkOrder balance amount
        wo = ro.work_order
        db.session.delete(ro)
        db.session.flush()
        if wo:
            recalculate_wo_balance(wo)
            
        db.session.commit()

        flash('Sub-Work Order deleted successfully and inventory adjusted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting Sub-Work Order: {e}', 'danger')
        
    return redirect(url_for('work_orders.work_order_view', wo_id=work_order_id))
