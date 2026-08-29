import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from decimal import Decimal
from datetime import date
from app import create_app
from app.extensions import db
from app.models import User, WorkOrder, ReleaseOrder, Farmer, FarmerMaterial, Material

@pytest.fixture
def client():
    app = create_app('testing')
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            
            # Create user
            user = User(username='admin_test', password_hash='hash', role='admin')
            db.session.add(user)
            
            # Create material with 100 stock
            m = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=Decimal('100.0'), received_qty=Decimal('0.0'))
            db.session.add(m)
            
            # Create WO & RO
            wo = WorkOrder(work_order_no='WO-100', po_no='PO-100', contract_amount=Decimal('100000.0'), balance_amount=Decimal('100000.0'))
            db.session.add(wo)
            db.session.flush()
            
            ro = ReleaseOrder(work_order_id=wo.id, release_no='1', po_no='PO-100', release_amount=Decimal('50000.0'), status='Pending')
            db.session.add(ro)
            db.session.flush()
            
            farmer = Farmer(release_order_id=ro.id, sr_number='SR-01', applicant_name='Ramesh Bhai', status='Active')
            db.session.add(farmer)
            db.session.commit()
            
            yield client
            
            db.session.remove()
            db.drop_all()

def test_draft_stock_deduction_and_reduction(client):
    with client.application.app_context():
        m = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        farmer = Farmer.query.first()
        ro = ReleaseOrder.query.first()
        
        assert m.current_stock == Decimal('100.0')
        
        # 1. Draft 10 poles for farmer
        fm = FarmerMaterial(farmer_id=farmer.id, pole_no='1', material_name=m.name, qty_required=Decimal('0.0'), qty_issued=Decimal('0.0'), qty_consumed=Decimal('10.0'))
        db.session.add(fm)
        db.session.commit()
        
        # Verify current stock decreased to 90
        assert m.current_stock == Decimal('90.0')
        
        # 2. Change draft from 10 to 9
        fm.qty_consumed = Decimal('9.0')
        db.session.commit()
        
        # Verify stock returned: 100 - 9 = 91
        assert m.current_stock == Decimal('91.0')
        
        # 3. Change draft to 0
        fm.qty_consumed = Decimal('0.0')
        db.session.commit()
        
        # Verify all 100 stock is available
        assert m.current_stock == Decimal('100.0')
