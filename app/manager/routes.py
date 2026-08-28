import os
import re
from decimal import Decimal
from datetime import date, datetime
from flask import request, render_template, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required

from app.extensions import db
from app.models import WorkOrder, ReleaseOrder, Farmer, FarmerMaterial, Material
from app.services.status import derive_ro_status
from app.services.excel_generator import generate_release_excel
from app.utils.helpers import resolve_item_code_from_name, find_material_by_code_or_name
from app.manager import manager

@manager.route('/', strict_slashes=False)
@login_required
def dashboard():
    work_orders = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    
    # Auto-derive each RO status from its farmers
    for wo in work_orders:
        for ro in wo.release_orders:
            derived = derive_ro_status(ro)
            if ro.status != derived:
                ro.status = derived
    db.session.commit()
    
    return render_template('manager/dashboard.html', work_orders=work_orders)

@manager.route('/farmer-status/<int:farmer_id>', methods=['POST'])
@login_required
def manager_farmer_status(farmer_id):
    """Update a single farmer's status to Active, Disputed, or Pending."""
    farmer = Farmer.query.get_or_404(farmer_id)
    ro = farmer.release_order
    new_status = request.form.get('status')
    
    if new_status not in ['Active', 'Disputed', 'Pending']:
        flash("Invalid status.", "danger")
        return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
    
    old_status = farmer.status
    
    if new_status == 'Disputed' and old_status in ['Active', 'Started']:
        for fm in farmer.materials:
            fm.qty_consumed = Decimal('0.0')
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
    ro.status = derive_ro_status(ro)
    db.session.commit()
    
    status_labels = {'Active': 'Activated', 'Disputed': 'Rejected (Disputed)', 'Pending': 'Reset to Pending'}
    flash(f"Farmer {farmer.applicant_name} — {status_labels.get(new_status, new_status)}.", "success")
    return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))

@manager.route('/update-status/<int:ro_id>', methods=['POST'])
@login_required
def manager_update_status(ro_id):
    """Bulk update: sets all farmers of the RO then auto-derives RO status."""
    ro = ReleaseOrder.query.get_or_404(ro_id)
    new_status = request.form.get('status')
    if new_status in ['Pending', 'Active', 'Disputed']:
        for f in ro.farmers:
            f.status = new_status
        ro.status = derive_ro_status(ro)
        db.session.commit()
        flash(f"Sub-Work Order #{ro.release_no} — all farmers set to {new_status}.", "success")
        if new_status == 'Active':
            return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
    return redirect(url_for('manager.dashboard'))

def material_sort_key(name):
    """Sorts material names according to the specific sequence in UGVCL Material Account Sheet."""
    if not name:
        return 9999
    name_clean = name.lower().strip()
    
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
    """Standardizes FarmerMaterial and MaterialReceiptItem names for a specific Release Order."""
    try:
        from app.models import MaterialReceiptItem
        ro = ReleaseOrder.query.get(ro_id)
        if not ro:
            return
            
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
    material_ids = {}
    for name in material_list:
        m = Material.query.filter_by(name=name).first()
        material_units[name] = m.unit if m else 'Nos'
        material_ids[name] = m.id if m else 0
        
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
            
        # Filter out EX poles — EX data is managed via the Taping modal only
        poles = [p for p in poles if p.upper() != 'EX']
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

    # Build EX taping data for display (read-only rows in the grid)
    farmer_ex_data = {}
    farmer_has_taping = {}
    for f in farmers:
        ex_fms = FarmerMaterial.query.filter_by(farmer_id=f.id, pole_no='EX').all()
        ex_materials = {}
        for fm in ex_fms:
            if fm.qty_consumed and fm.qty_consumed > 0:
                ex_materials[fm.material_name] = float(fm.qty_consumed)
        farmer_ex_data[f.id] = ex_materials
        farmer_has_taping[f.id] = len(ex_materials) > 0

    status_counts = {}
    for f in farmers:
        status_counts[f.status] = status_counts.get(f.status, 0) + 1
        
    material_stocks = {}
    for name in material_list:
        m = Material.query.filter_by(name=name).first()
        material_stocks[name] = float(m.current_stock) if m else 0.0
            
    return {
        'ro': ro, 'wo': wo, 'farmers': farmers, 'materials': material_list,
        'material_units': material_units, 'material_ids': material_ids,
        'required_map': required_map,
        'required_pole_map': required_pole_map, 'consumption_map': consumption_map,
        'farmer_poles': farmer_poles, 'material_stocks': material_stocks,
        'farmer_ex_data': farmer_ex_data, 'farmer_has_taping': farmer_has_taping,
        'status_counts': status_counts, 'float': float, 'isinstance': isinstance, 'Decimal': Decimal
    }

@manager.route('/farmer/<int:farmer_id>/taping', methods=['GET'])
@login_required
def manager_get_taping(farmer_id):
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

@manager.route('/farmer/<int:farmer_id>/taping', methods=['POST'])
@login_required
def manager_save_taping(farmer_id):
    farmer = Farmer.query.get_or_404(farmer_id)
    ro = farmer.release_order
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if ro and ro.status == 'Completed':
        if is_ajax:
            return jsonify({'status': 'error', 'message': 'This Sub-Work Order is finalized and locked.'}), 400
        flash("This Sub-Work Order is finalized and locked.", "danger")
        return redirect(url_for('manager.active_farmers', ro_id=ro.id))
        
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

    
    # Build response data for AJAX
    if is_ajax:
        ex_fms = FarmerMaterial.query.filter_by(farmer_id=farmer_id, pole_no='EX').all()
        ex_materials = []
        for fm in ex_fms:
            if fm.qty_consumed and fm.qty_consumed > 0:
                ex_materials.append({
                    'material_name': fm.material_name,
                    'qty_consumed': float(fm.qty_consumed)
                })
        return jsonify({
            'status': 'success',
            'message': 'Taping (EX) details updated successfully.',
            'taping_price': float(farmer.ex or 0.0),
            'materials': ex_materials,
            'has_taping': len(ex_materials) > 0
        })
    
    flash("Taping (EX) details updated successfully.", "success")
    return redirect(url_for('manager.active_farmers', ro_id=ro.id))

@manager.route('/sub-order/<int:ro_id>')
@login_required
def sub_order_detail(ro_id):
    ctx = get_sub_order_context(ro_id)
    return render_template('manager/sub_order_detail.html', **ctx)

@manager.route('/sub-order/<int:ro_id>/active-farmers')
@login_required
def active_farmers(ro_id):
    ctx = get_sub_order_context(ro_id)
    return render_template('manager/active_farmers.html', **ctx)

@manager.route('/sub-order/<int:ro_id>/save', methods=['POST'])
@login_required
def save_consumption(ro_id):
    ro = ReleaseOrder.query.get_or_404(ro_id)
    if ro.status == 'Completed':
        flash("This Sub-Work Order is finalized and locked.", "danger")
        return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
        
    action = request.form.get('action') # 'draft' or 'submit'
    
    farmers = ro.farmers
    material_names = set()
    all_m = Material.query.all()
    for m in all_m:
        if m.opening_stock > 0 or m.received_qty > 0 or m.issued_qty > 0 or m.consumed_qty > 0:
            material_names.add(m.name)
            
    material_list = list(material_names)
    
    available_stocks = {}
    for m_name in material_list:
        m = Material.query.filter_by(name=m_name).first()
        if m:
            active_farmers_consumed = Decimal('0.0')
            for farmer in farmers:
                if farmer.status in ['Active', 'Started']:
                    for fm in farmer.materials:
                        if fm.material_name == m_name:
                            active_farmers_consumed += fm.qty_consumed or Decimal('0.0')
            available_stocks[m_name] = m.current_stock + active_farmers_consumed
        else:
            available_stocks[m_name] = Decimal('0.0')

    
    proposed_consumption = {}
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
            # Skip EX poles — they are managed via the Taping modal
            if new_p and new_p.upper() != 'EX' and old_p.upper() != 'EX':
                submitted_poles[old_p] = new_p
                
        if not submitted_poles:
            submitted_poles['1'] = '1'
            for m_name in material_list:
                m = Material.query.filter_by(name=m_name).first()
                m_id = m.id if m else 0
                input_key_old = f"consumed_{f.id}_{m_id}"
                raw_val = request.form.get(input_key_old)
                if raw_val is None:
                    input_key_new = f"consumed_{f.id}_1_{m_id}"
                    raw_val = request.form.get(input_key_new)
                if raw_val is None:
                    # fallback to name
                    input_key_old_fb = f"consumed_{f.id}_{m_name}"
                    raw_val = request.form.get(input_key_old_fb)
                    if raw_val is None:
                        input_key_new_fb = f"consumed_{f.id}_1_{m_name}"
                        raw_val = request.form.get(input_key_new_fb, '')
                raw_val = raw_val.strip() if raw_val else ''
                val = Decimal(raw_val) if raw_val else Decimal('0.0')
                proposed_consumption[m_name] += val
        else:
            for old_p, new_p in submitted_poles.items():
                for m_name in material_list:
                    m = Material.query.filter_by(name=m_name).first()
                    m_id = m.id if m else 0
                    input_key = f"consumed_{f.id}_{old_p}_{m_id}"
                    raw_val = request.form.get(input_key)
                    if raw_val is None:
                        # fallback to name
                        input_key_fb = f"consumed_{f.id}_{old_p}_{m_name}"
                        raw_val = request.form.get(input_key_fb, '')
                    raw_val = raw_val.strip() if raw_val else ''
                    val = Decimal(raw_val) if raw_val else Decimal('0.0')
                    proposed_consumption[m_name] += val

    for m_name, proposed_val in proposed_consumption.items():
        if proposed_val > 0:
            m = Material.query.filter_by(name=m_name).first()
            if not m:
                msg = f"Material '{m_name}' does not exist in inventory."
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'status': 'error', 'message': msg}), 400
                flash(msg, "danger")
                return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
            
            available_stock = available_stocks.get(m_name, Decimal('0.0'))
            
            if proposed_val > available_stock:
                msg = f"Error: Insufficient stock for '{m_name}'. Available: {float(available_stock)} {m.unit}, Requested: {float(proposed_val)} {m.unit}."
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'status': 'error', 'message': msg}), 400
                flash(msg, "danger")
                return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
                
    for f in farmers:
        if f.status not in ['Active', 'Started']:
            continue
            
        pole_keys = [k for k in request.form.keys() if k.startswith(f"pole_name_{f.id}_")]
        
        submitted_poles = {}
        for pk in pole_keys:
            old_p = pk.replace(f"pole_name_{f.id}_", "")
            new_p = request.form.get(pk, '').strip()
            # Skip EX poles — they are managed via the Taping modal
            if new_p and new_p.upper() != 'EX' and old_p.upper() != 'EX':
                submitted_poles[old_p] = new_p
                
        if not submitted_poles:
            submitted_poles['1'] = '1'
            for m_name in material_list:
                m = Material.query.filter_by(name=m_name).first()
                m_id = m.id if m else 0
                input_key_old = f"consumed_{f.id}_{m_id}"
                raw_val = request.form.get(input_key_old)
                if raw_val is None:
                    input_key_new = f"consumed_{f.id}_1_{m_id}"
                    raw_val = request.form.get(input_key_new)
                if raw_val is None:
                    # fallback to name
                    input_key_old_fb = f"consumed_{f.id}_{m_name}"
                    raw_val = request.form.get(input_key_old_fb)
                    if raw_val is None:
                        input_key_new_fb = f"consumed_{f.id}_1_{m_name}"
                        raw_val = request.form.get(input_key_new_fb, '')
                        
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
                        item_code=m.item_code if m else resolve_item_code_from_name(m_name),
                        qty_required=Decimal('0.0'),
                        qty_issued=Decimal('0.0'),
                        qty_consumed=val
                    )
                    db.session.add(fm)
        else:
            for old_p, new_p in submitted_poles.items():
                for m_name in material_list:
                    m = Material.query.filter_by(name=m_name).first()
                    m_id = m.id if m else 0
                    input_key = f"consumed_{f.id}_{old_p}_{m_id}"
                    raw_val = request.form.get(input_key)
                    if raw_val is None:
                        # fallback to name
                        input_key_fb = f"consumed_{f.id}_{old_p}_{m_name}"
                        raw_val = request.form.get(input_key_fb, '')
                    raw_val = raw_val.strip() if raw_val else ''
                    val = Decimal(raw_val) if raw_val else Decimal('0.0')
                    
                    fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=old_p).first()
                    if fm:
                        fm.pole_no = new_p
                        fm.qty_consumed = val
                    else:
                        fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=m_name, pole_no=new_p).first()
                        if fm:
                            fm.qty_consumed = val
                        else:
                            fm = FarmerMaterial(
                                farmer_id=f.id,
                                pole_no=new_p,
                                material_name=m_name,
                                item_code=m.item_code if m else resolve_item_code_from_name(m_name),
                                qty_required=Decimal('0.0'),
                                qty_issued=Decimal('0.0'),
                                qty_consumed=val
                            )
                            db.session.add(fm)
                            
            all_db_poles = db.session.query(FarmerMaterial.pole_no).filter(
                FarmerMaterial.farmer_id == f.id,
                FarmerMaterial.pole_no.isnot(None)
            ).distinct().all()
            all_db_poles = [p[0] for p in all_db_poles if p[0]]
            
            new_pole_names = set(submitted_poles.values())
            for db_p in all_db_poles:
                # Never delete EX poles here — they are managed via the Taping modal
                if db_p.upper() == 'EX':
                    continue
                if db_p not in new_pole_names:
                    fms_to_clean = FarmerMaterial.query.filter_by(farmer_id=f.id, pole_no=db_p).all()
                    for fm in fms_to_clean:
                        if (fm.qty_required or 0) > 0 or (fm.qty_issued or 0) > 0:
                            fm.qty_consumed = Decimal('0.0')
                        else:
                            db.session.delete(fm)

                
    if action == 'submit':
        for f in farmers:
            if f.status in ['Active', 'Started']:
                f.status = 'Completed'
        flash_msg = f"Sub-Work Order #{ro.release_no} consumption sheet finalized and submitted."
        flash(flash_msg, "success")
    else:
        for f in farmers:
            if f.status == 'Active':
                f.status = 'Started'
        flash_msg = f"Sub-Work Order #{ro.release_no} consumption draft saved."
        flash(flash_msg, "success")
    
    ro.status = derive_ro_status(ro)
    db.session.flush()
    
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
    
    # Return JSON for AJAX requests (no page reload)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success', 'message': flash_msg})
    
    if action == 'submit':
        return redirect(url_for('manager.dashboard'))
    if request.referrer and 'active-farmers' in request.referrer:
        return redirect(url_for('manager.active_farmers', ro_id=ro.id))
    return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))

@manager.route('/sub-order/<int:ro_id>/download-excel')
@login_required
def download_excel(ro_id):
    ro = ReleaseOrder.query.get_or_404(ro_id)
    
    has_pending = Farmer.query.filter_by(release_order_id=ro.id, status='Pending').first() is not None
    if has_pending:
        flash("Cannot generate Excel spreadsheet when there are pending farmers. Please activate or reject all farmers first.", "warning")
        return redirect(url_for('manager.sub_order_detail', ro_id=ro.id))
        
    excel_stream = generate_release_excel(ro)
    filename = f"Release_{ro.release_no}_Account.xls"
    
    return send_file(
        excel_stream,
        mimetype="application/vnd.ms-excel",
        as_attachment=True,
        download_name=filename
    )
