import os
from decimal import Decimal
from datetime import datetime, date
from flask import request, render_template, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Material, MaterialReceipt, MaterialReceiptItem, CreditReceipt, DocumentVault, Farmer, FarmerMaterial
from app.utils.decorators import admin_required
from app.utils.helpers import resolve_item_code_from_name, find_material_by_code_or_name
from app.inventory import inventory

@inventory.route('/', methods=['GET', 'POST'], strict_slashes=False)
@admin_required
def list_inventory():
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
            
            m = Material.query.filter_by(name=material_name).first()
            if m:
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
            
        return redirect(url_for('inventory.list_inventory'))
        
    materials = Material.query.all()
    receipts = MaterialReceipt.query.filter(MaterialReceipt.release_order_id.is_(None)).all()
    credit_receipts = CreditReceipt.query.all()
    return render_template('inventory/index.html', materials=materials, receipts=receipts, credit_receipts=credit_receipts, today_date=date.today().strftime('%Y-%m-%d'))

@inventory.route('/update-price', methods=['POST'])
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

@inventory.route('/lookup-gate-pass/<mr_number>', methods=['GET'])
@admin_required
def inventory_lookup_gate_pass(mr_number):
    from app.services.ocr_parser import normalize_mr_number
    
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

@inventory.route('/material-history/<path:material_name>', methods=['GET'])
@admin_required
def inventory_material_history(material_name):
    try:
        m = Material.query.filter_by(name=material_name).first()
        if not m:
            return jsonify({'success': False, 'message': 'Material not found'})
            
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
            
        debits = []
        from collections import defaultdict
        farmer_group = defaultdict(lambda: {'issued': 0.0, 'consumed': 0.0, 'farmer_obj': None})
        
        from sqlalchemy import or_
        if m.item_code:
            farmer_materials = FarmerMaterial.query.filter(
                or_(
                    FarmerMaterial.item_code == m.item_code,
                    FarmerMaterial.material_name == material_name
                )
            ).all()
        else:
            farmer_materials = FarmerMaterial.query.filter_by(material_name=material_name).all()
            
        for fm in farmer_materials:
            farmer = fm.farmer
            if farmer.status not in ['Material Issued', 'Started', 'Completed']:
                continue
            farmer_group[farmer.id]['issued'] += float(fm.qty_issued or 0.0)
            farmer_group[farmer.id]['consumed'] += float(fm.qty_consumed or 0.0)
            farmer_group[farmer.id]['farmer_obj'] = farmer
            
        for f_id, data in farmer_group.items():
            qty = max(data['issued'], data['consumed'])
            if qty <= 0:
                continue
            farmer = data['farmer_obj']
            rel_no = farmer.release_order.release_no if farmer.release_order else 'N/A'
            f_date = farmer.date.strftime('%d-%b-%Y') if farmer.date else "N/A"
            debits.append({
                'date': f_date,
                'qty': qty,
                'farmer': farmer.applicant_name,
                'release_no': rel_no,
                'status': farmer.status
            })
            
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
        return jsonify({'success': False, 'message': f'Parsing failed: {str(e)}'})

@inventory.route('/check-mr-exists/<mr_number>', methods=['GET'])
@admin_required
def check_mr_exists(mr_number):
    exists = MaterialReceipt.query.filter_by(receipt_no=mr_number).first() is not None
    return jsonify({'exists': exists})

@inventory.route('/upload-gate-pass', methods=['POST'])
@admin_required
def inventory_upload_gate_pass():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            from app.services.ocr_parser import extract_text_from_pdf, parse_gate_pass_text
            extracted_text = extract_text_from_pdf(file_path)
            parsed_data = parse_gate_pass_text(extracted_text)
            doc_type = 'Gate Pass PDF'
        else:
            from app.services.ocr_parser import parse_gate_pass_image
            parsed_data = parse_gate_pass_image(file_path)
            doc_type = 'Gate Pass Photo'
        
        vault_doc = DocumentVault(
            doc_type=doc_type,
            filename=filename,
            file_path=f"/uploads/{filename}"
        )
        db.session.add(vault_doc)
        db.session.commit()
        
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
            'file_path': f"/uploads/{filename}",
            'vault_doc_id': vault_doc.id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR Parsing failed: {str(e)}'})

@inventory.route('/save-gate-pass', methods=['POST'])
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
            
        receipt = MaterialReceipt.query.filter_by(receipt_no=mr_number).first()
        if not receipt:
            receipt = MaterialReceipt(
                release_order_id=None,
                receipt_no=mr_number,
                date=receipt_date
            )
            db.session.add(receipt)
            db.session.flush()

        
        for it in items:
            material_name = it.get('material_name')
            qty = Decimal(str(it.get('qty', '0')))
            rate = Decimal(str(it.get('rate', '0')))
            is_new = it.get('is_new', False)
            unit = it.get('unit', 'Nos')
            item_code = it.get('item_code')
            
            if is_new:
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
            
        if vault_doc_id:
            vault_doc = DocumentVault.query.get(vault_doc_id)
            if vault_doc:
                vault_doc.related_id = receipt.id
                vault_doc.doc_type = 'Material Receipt'
                
        db.session.commit()
        flash(f'Gate Pass MR-{mr_number} imported successfully! Stock updated.', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@inventory.route('/update-material', methods=['POST'])
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

@inventory.route('/save-debit', methods=['POST'])
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
        
        import uuid
        sr_number = f"SR-{uuid.uuid4().hex[:8].upper()}"
        
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
        db.session.flush()
        
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

@inventory.route('/debit/delete/<int:farmer_id>', methods=['POST'])
@admin_required
def debit_delete(farmer_id):
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
    return redirect(url_for('inventory.list_inventory'))

@inventory.route('/debit-history', methods=['GET'])
@admin_required
def inventory_debit_history():
    try:
        farmers = Farmer.query.order_by(Farmer.date.desc(), Farmer.id.desc()).all()
        data = []
        for f in farmers:
            items = []
            for fm in f.materials:
                qty = max(Decimal(str(fm.qty_issued or 0.0)), Decimal(str(fm.qty_consumed or 0.0)))
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

@inventory.route('/credit-history', methods=['GET'])
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

@inventory.route('/receipt/delete/<int:receipt_id>', methods=['POST'])
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
    return redirect(url_for('inventory.list_inventory'))

@inventory.route('/credit/delete/<int:credit_id>', methods=['POST'])
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
    return redirect(url_for('inventory.list_inventory'))
