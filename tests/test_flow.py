import os
import pytest
from decimal import Decimal
from datetime import date
from models import db, User, WorkOrder, ReleaseOrder, Material, MaterialReceipt, MaterialReceiptItem, CreditReceipt, DocumentVault, Farmer, FarmerMaterial
from app import app

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(TEST_DIR, 'samples')


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            from werkzeug.security import generate_password_hash
            # Seed a backward-compatible test user (admin role) for existing tests
            user = User.query.filter_by(username='test_user').first()
            if not user:
                user = User(username='test_user', password_hash=generate_password_hash('password', method='pbkdf2:sha256'), role='admin')
                db.session.add(user)
            # Seed admin user
            admin = User.query.filter_by(username='admin@gmail.com').first()
            if not admin:
                admin = User(username='admin@gmail.com', password_hash=generate_password_hash('44113290', method='pbkdf2:sha256'), role='admin')
                db.session.add(admin)
            # Seed manager user
            manager = User.query.filter_by(username='manager@gmail.com').first()
            if not manager:
                manager = User(username='manager@gmail.com', password_hash=generate_password_hash('44113290', method='pbkdf2:sha256'), role='manager')
                db.session.add(manager)
            # Seed default test materials
            pole = Material.query.filter_by(name='PSC Pole 8 MTR').first()
            if pole:
                pole.opening_stock = 100.0
            else:
                pole = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
                db.session.add(pole)
                
            cable = Material.query.filter_by(name='Conducto 34mm 2wire').first()
            if cable:
                cable.opening_stock = 1000.0
            else:
                cable = Material(name='Conducto 34mm 2wire', unit='Mtr', opening_stock=1000.0)
                db.session.add(cable)
            db.session.commit()
        yield client


def login_as_admin(client):
    """Helper to log in as admin user for tests requiring admin access."""
    return client.post('/login', data={'username': 'admin@gmail.com', 'password': '44113290'}, follow_redirects=True)


def login_as_manager(client):
    """Helper to log in as manager user for tests requiring manager access."""
    return client.post('/login', data={'username': 'manager@gmail.com', 'password': '44113290'}, follow_redirects=True)

def test_ocr_parsing():
    from ocr_parser import parse_gate_pass_text
    
    # Test raw text parsing of gate pass
    mock_gp_text = """
    MR Number - 99999999
    Requestor - Mr. NAYANKUMAR HIMMATLAL PATEL
    Description - PO-102695-12 ERECTION OF HT LT AND TC LINE
    
    Line Item Item Description From To UOM Qty Qty Issue
    No. Code Subinv Subinv Req. Issued Date
    5 0103000002 G I WIRE 8 SWG 4MM U4210 /Locator KG 86 36.88 19-JUN-2026
    6 0102000031 ALL ALLUMINIUM ALLOY CONDUCTOR 34 SQMM WEASEL KM 3.412 2.014 19-JUN-2026
    """
    
    parsed = parse_gate_pass_text(mock_gp_text)
    assert parsed['mr_number'] == '99999999'
    assert parsed['requestor'] == 'Mr. NAYANKUMAR HIMMATLAL PATEL'
    assert len(parsed['items']) == 2
    assert parsed['items'][0]['item_code'] == '0103000002'
    assert parsed['items'][0]['description'] == 'G I WIRE 8 SWG 4MM'
    assert parsed['items'][0]['uom'] == 'KG'
    assert parsed['items'][0]['qty_issued'] == 36.88


def test_inventory_ocr_and_pricing(client):
    with app.app_context():
        login_as_admin(client)
        # 1. Test rate updating endpoint
        mat = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not mat:
            mat = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
            db.session.add(mat)
            db.session.commit()
            
        update_res = client.post('/inventory/update-price', json={
            'material_id': mat.id,
            'price': 14500.50
        })
        assert update_res.status_code == 200
        assert update_res.get_json()['success'] is True
        
        # Verify rate saved in DB
        db.session.refresh(mat)
        assert float(mat.unit_price) == 14500.50
        
        # 2. Test saving parsed gate pass
        payload = {
            'mr_number': '16535255',
            'date': '2026-06-19',
            'release_order_id': None,
            'items': [
                {
                    'material_name': 'PSC Pole 8 MTR',
                    'qty': 10,
                    'rate': 14500.50,
                    'is_new': False,
                    'unit': 'Nos'
                },
                {
                    'material_name': 'New Scanned Material Item',
                    'qty': 25,
                    'rate': 55.00,
                    'is_new': True,
                    'unit': 'Nos'
                }
            ],
            'vault_doc_id': None
        }
        
        save_res = client.post('/inventory/save-gate-pass', json=payload)
        assert save_res.status_code == 200
        assert save_res.get_json()['success'] is True
        
        # Verify stock update
        pole_after = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        assert float(pole_after.received_qty) == 10.0
        
        new_mat = Material.query.filter_by(name='New Scanned Material Item').first()
        assert new_mat is not None
        assert float(new_mat.received_qty) == 25.0
        assert float(new_mat.unit_price) == 55.00

        # 3. Test lookup endpoint for pre-verified gate pass
        lookup_res = client.get('/inventory/lookup-gate-pass/16535255')
        assert lookup_res.status_code == 200
        lookup_data = lookup_res.get_json()
        assert lookup_data['success'] is True
        assert lookup_data['mr_number'] == '16535255'
        assert len(lookup_data['items']) == 12
        assert lookup_data['items'][0]['item_code'] == '2601000040'
        
        # Test lookup endpoint with invalid format or unknown number
        lookup_res_fail = client.get('/inventory/lookup-gate-pass/99999999')
        assert lookup_res_fail.status_code == 200
        assert lookup_res_fail.get_json()['success'] is False

        # 4. Test history endpoint and Material properties
        history_res = client.get('/inventory/material-history/PSC Pole 8 MTR')
        assert history_res.status_code == 200
        history_data = history_res.get_json()
        assert history_data['success'] is True
        assert len(history_data['credits']) > 0
        assert history_data['credits'][0]['qty'] == 10.0
        assert 'ledger' in history_data
        assert len(history_data['ledger']) > 0

        # Verify model properties latest_credit, latest_debit, and clean amount properties
        pole_mat = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        assert pole_mat.latest_credit != 'N/A'
        assert '+10.0 Nos' in pole_mat.latest_credit
        assert pole_mat.latest_credit_amount == '+10.0 Nos'
        assert pole_mat.latest_debit_amount == 'N/A'


def test_receipt_delete(client):
    with app.app_context():
        login_as_admin(client)
        # Create a material and receipt
        mat = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not mat:
            mat = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
            db.session.add(mat)
            db.session.commit()

        # Record starting received qty (may have been modified by previous tests)
        starting_received = float(mat.received_qty)

        receipt = MaterialReceipt(
            release_order_id=None,
            receipt_no='MR-DEL-TEST',
            date=date.today()
        )
        db.session.add(receipt)
        db.session.commit()
        
        item = MaterialReceiptItem(
            receipt_id=receipt.id,
            material_name='PSC Pole 8 MTR',
            qty=Decimal('10.0')
        )
        db.session.add(item)
        mat.received_qty += Decimal('10.0')
        db.session.commit()

        receipt_id = receipt.id
        
        # Delete the receipt
        response = client.get(f'/inventory/receipt/delete/{receipt_id}')
        assert response.status_code == 302
        assert MaterialReceipt.query.get(receipt_id) is None

        # Verify stock reverted to starting value
        db.session.refresh(mat)
        assert float(mat.received_qty) == starting_received


def test_credit_delete(client):
    with app.app_context():
        login_as_admin(client)
        mat = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not mat:
            mat = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
            db.session.add(mat)
            db.session.commit()

        # Record starting received qty
        starting_received = float(mat.received_qty)

        cr = CreditReceipt(
            cr_number='CR-DEL-TEST',
            date=date.today(),
            material_name='PSC Pole 8 MTR',
            qty=Decimal('2.0')
        )
        db.session.add(cr)
        mat.received_qty += Decimal('2.0')
        db.session.commit()

        cr_id = cr.id

        response = client.get(f'/inventory/credit/delete/{cr_id}')
        assert response.status_code == 302
        assert CreditReceipt.query.get(cr_id) is None

        db.session.refresh(mat)
        assert float(mat.received_qty) == starting_received


def test_root_redirects_to_inventory(client):
    """Root URL should redirect to /inventory for admin users."""
    login_as_admin(client)
    response = client.get('/')
    assert response.status_code == 302
    assert '/inventory' in response.headers['Location']


def test_inventory_debit_flow(client):
    with app.app_context():
        login_as_admin(client)
        # Setup materials
        from models import Farmer
        mat = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not mat:
            mat = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
            db.session.add(mat)
        else:
            mat.opening_stock = 100.0
            mat.issued_qty = 0.0
        db.session.commit()

        # 1. Test update-material endpoint
        update_mat_res = client.post('/inventory/update-material', json={
            'material_id': mat.id,
            'name': 'PSC Pole 8 MTR',
            'item_code': '2601000040',
            'unit': 'Nos',
            'price': 14500.50
        })
        assert update_mat_res.status_code == 200
        assert update_mat_res.get_json()['success'] is True
        
        db.session.refresh(mat)
        assert mat.item_code == '2601000040'
        assert float(mat.unit_price) == 14500.50

        # 2. Record a debit (material issue)
        start_stock = float(mat.current_stock)
        debit_payload = {
            'farmer_name': 'Test Farmer Name',
            'village': 'Bhildi',
            'po_no': '102695',
            'release_no': '1',
            'date': '2026-06-20',
            'items': [
                {
                    'material_name': 'PSC Pole 8 MTR',
                    'qty': 5
                }
            ]
        }
        
        save_debit_res = client.post('/inventory/save-debit', json=debit_payload)
        assert save_debit_res.status_code == 200
        assert save_debit_res.get_json()['success'] is True

        # Check stock is updated (issued_qty should be 5.0, current_stock should be start_stock - 5.0)
        db.session.refresh(mat)
        assert float(mat.issued_qty) == 5.0
        assert float(mat.current_stock) == start_stock - 5.0

        # 3. Check debit history endpoint
        history_res = client.get('/inventory/debit-history')
        assert history_res.status_code == 200
        history_data = history_res.get_json()
        assert history_data['success'] is True
        assert len(history_data['debits']) > 0
        assert history_data['debits'][0]['farmer_name'] == 'Test Farmer Name'
        assert history_data['debits'][0]['po_no'] == '102695'
        assert history_data['debits'][0]['items'][0]['qty'] == 5.0

        # Check credit history endpoint
        credit_history_res = client.get('/inventory/credit-history')
        assert credit_history_res.status_code == 200
        assert credit_history_res.get_json()['success'] is True

        # 4. Delete the debit and verify stock is restored
        farmer_id = history_data['debits'][0]['id']
        delete_res = client.get(f'/inventory/debit/delete/{farmer_id}')
        assert delete_res.status_code == 302

        db.session.refresh(mat)
        assert float(mat.issued_qty) == 0.0
        assert float(mat.current_stock) == start_stock
        assert Farmer.query.get(farmer_id) is None


def test_work_orders_flow(client):
    with app.app_context():
        login_as_admin(client)
        # Count starting work orders
        start_count = WorkOrder.query.count()
        
        # 1. Create a work order manually
        payload = {
            'work_order_no': 'WO-TEST-999',
            'po_no': '999111',
            'tender_id': '88888',
            'rfq_no': '77777',
            'pr_no': '66666',
            'approval_no': 'APP-999',
            'contractor_name': 'Test Contractor Inc',
            'contract_amount': '500000.00',
            'start_date': '2026-06-01',
            'end_date': '2026-09-01'
        }
        
        response = client.post('/work-orders', data=payload)
        assert response.status_code == 302 # redirect
        
        # Verify it was added
        assert WorkOrder.query.count() == start_count + 1
        wo = WorkOrder.query.filter_by(work_order_no='WO-TEST-999').first()
        assert wo is not None
        assert float(wo.contract_amount) == 500000.00
        assert float(wo.balance_amount) == 500000.00
        assert wo.start_date.strftime('%Y-%m-%d') == '2026-06-01'
        
        # 2. Check details API
        details_res = client.get(f'/work-orders/details/{wo.id}')
        assert details_res.status_code == 200
        data = details_res.get_json()
        assert data['success'] is True
        assert data['work_order_no'] == 'WO-TEST-999'
        assert data['contractor_name'] == 'Test Contractor Inc'
        assert data['contract_amount'] == 500000.00
        
        # 2a. Check details page view
        view_res = client.get(f'/work-orders/{wo.id}')
        assert view_res.status_code == 200
        assert b'WO-TEST-999' in view_res.data

        # 2b. Add a Sub-Work Order manually to this Work Order
        sub_payload = {
            'work_order_id': wo.id,
            'release_no': '1',
            'po_no': '999111',
            'release_amount': '50000.00',
            'scheme': 'ND',
            'release_date': '2026-06-21'
        }
        sub_res = client.post('/work-orders/add-release-order', data=sub_payload)
        assert sub_res.status_code == 302 # redirect
        
        # Verify Sub-WO is created and parent balance is updated
        db.session.refresh(wo)
        assert float(wo.balance_amount) == 450000.00
        ro = ReleaseOrder.query.filter_by(work_order_id=wo.id, release_no='1').first()
        assert ro is not None
        assert float(ro.release_amount) == 50000.00
        
        # 3. Test OCR-assisted saving
        ocr_payload = {
            'work_order_no': 'WO-OCR-123',
            'po_no': '123456',
            'tender_id': '3333',
            'rfq_no': '4444',
            'pr_no': '5555',
            'approval_no': 'APP-123',
            'contractor_name': 'OCR Contractor Ltd',
            'contract_amount': '150000.50',
            'vault_doc_id': None,
            'pdf_path': '/static/uploads/wo_test.pdf',
            'start_date': '2026-05-15',
            'end_date': '2026-08-15'
        }
        
        save_res = client.post('/work-orders/save-ocr', json=ocr_payload)
        assert save_res.status_code == 200
        assert save_res.get_json()['success'] is True
        
        # Verify OCR work order was added
        wo_ocr = WorkOrder.query.filter_by(work_order_no='WO-OCR-123').first()
        assert wo_ocr is not None
        assert float(wo_ocr.contract_amount) == 150000.50
        assert float(wo_ocr.balance_amount) == 150000.50
        
        # 3b. Test OCR-assisted saving of a Sub-Work Order for this OCR Work Order
        sub_ocr_payload = {
            'work_order_id': wo_ocr.id,
            'release_no': '2',
            'po_no': '123456',
            'release_amount': '30000.25',
            'remaining_amount': '30000.25',
            'scheme': 'HP',
            'release_date': '2026-06-20',
            'vault_doc_id': None,
            'pdf_path': '/static/uploads/ro_test.pdf'
        }
        sub_ocr_res = client.post('/work-orders/save-release-order-ocr', json=sub_ocr_payload)
        assert sub_ocr_res.status_code == 200
        assert sub_ocr_res.get_json()['success'] is True
        
        # Verify Sub-WO is created and parent balance is updated
        db.session.refresh(wo_ocr)
        assert float(wo_ocr.balance_amount) == 120000.25
        ro_ocr = ReleaseOrder.query.filter_by(work_order_id=wo_ocr.id, release_no='2').first()
        assert ro_ocr is not None
        assert float(ro_ocr.release_amount) == 30000.25
        
        # 4. Delete and verify deletion
        delete_res = client.get(f'/work-orders/delete/{wo.id}')
        assert delete_res.status_code == 302
        assert WorkOrder.query.get(wo.id) is None
        
        delete_ocr_res = client.get(f'/work-orders/delete/{wo_ocr.id}')
        assert delete_ocr_res.status_code == 302
        assert WorkOrder.query.get(wo_ocr.id) is None

def test_farmer_pdf_upload_and_save_flow(client):
    with app.app_context():
        login_as_admin(client)
        # Create a work order and release order to link to
        wo = WorkOrder(
            work_order_no='WO-FARM-1',
            po_no='777888',
            contract_amount=Decimal('200000.00'),
            balance_amount=Decimal('200000.00')
        )
        db.session.add(wo)
        db.session.flush()
        
        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no='1',
            po_no='777888',
            release_amount=Decimal('100000.00'),
            remaining_amount=Decimal('100000.00'),
            scheme='ND'
        )
        db.session.add(ro)
        db.session.commit()
        
        ro_id = ro.id
        
        # We will upload the actual PDF to trigger the pre-verified Release 1 list
        pdf_path = os.path.join(SAMPLES_DIR, 'WhatsApp Scan 2026-04-07 at 11.35.34.pdf')
        
        with open(pdf_path, 'rb') as f:
            from io import BytesIO
            data = {
                'file': (BytesIO(f.read()), 'WhatsApp Scan 2026-04-07 at 11.35.34.pdf')
            }
            res = client.post('/work-orders/upload-farmer-list', data=data, content_type='multipart/form-data')
            
        assert res.status_code == 200
        res_json = res.get_json()
        assert res_json['success'] is True
        assert len(res_json['farmers']) == 19
        assert res_json['farmers'][0]['applicant_name'] == 'GADHAVI AMARDAN HAMIRJI'
        assert res_json['farmers'][0]['village'] == 'THIKARIYA'
        assert res_json['farmers'][0]['lt2'] == 0.082
        
        # Test saving the farmers
        save_payload = {
            'release_order_id': ro_id,
            'farmers': res_json['farmers'],
            'vault_doc_id': res_json['vault_doc_id']
        }
        save_res = client.post('/work-orders/save-farmer-list-ocr', json=save_payload)
        assert save_res.status_code == 200
        assert save_res.get_json()['success'] is True
        
        # Verify farmers saved in database
        from models import Farmer, FarmerMaterial
        farmers_in_db = Farmer.query.filter_by(release_order_id=ro_id).all()
        assert len(farmers_in_db) == 19
        
        f1 = Farmer.query.filter_by(release_order_id=ro_id, applicant_name='GADHAVI AMARDAN HAMIRJI').first()
        assert f1 is not None
        assert f1.village == 'THIKARIYA'
        assert float(f1.lt2) == 0.082
        
        # Verify materials created
        m1 = FarmerMaterial.query.filter_by(farmer_id=f1.id, material_name='Conducto 34mm 2wire').first()
        assert m1 is not None
        assert float(m1.qty_required) == 82.0 # 0.082 * 1000


def test_combined_pdf_flow(client):
    with app.app_context():
        login_as_admin(client)
        # Setup WorkOrder
        wo = WorkOrder(
            work_order_no='WO-COMBINED-TEST',
            po_no='102600',
            contract_amount=Decimal('1500000.00'),
            balance_amount=Decimal('1500000.00')
        )
        db.session.add(wo)
        db.session.commit()
        
        wo_id = wo.id
        
        pdf_path = os.path.join(SAMPLES_DIR, 'media__1782024645219.pdf')
        
        # 1. Test OCR upload endpoint for Release Order
        with open(pdf_path, 'rb') as f:
            from io import BytesIO
            data = {
                'file': (BytesIO(f.read()), 'media__1782024645219.pdf')
            }
            res = client.post('/work-orders/upload-release-order', data=data, content_type='multipart/form-data')
            
        assert res.status_code == 200
        res_json = res.get_json()
        assert res_json['success'] is True
        assert res_json['release_no'] == '5'
        assert len(res_json['materials']) == 26
        assert len(res_json['farmers']) == 8
        
        # 2. Test saving OCR release order
        save_payload = {
            'work_order_id': wo_id,
            'release_no': '5',
            'po_no': '102600',
            'release_amount': '138469.29',
            'remaining_amount': '2599.02',
            'scheme': 'DZ',
            'release_date': '2025-12-23',
            'vault_doc_id': res_json['vault_doc_id'],
            'pdf_path': res_json['file_path'],
            'receipt_no': '16409883',
            'materials': res_json['materials'],
            'farmers': res_json['farmers']
        }
        save_res = client.post('/work-orders/save-release-order-ocr', json=save_payload)
        assert save_res.status_code == 200
        print("SAVE RES:", save_res.get_json())
        assert save_res.get_json()['success'] is True
        
        # Verify db entries
        ro = ReleaseOrder.query.filter_by(work_order_id=wo_id, release_no='5').first()
        assert ro is not None
        assert float(ro.release_amount) == 138469.29
        
        # Verify materials receipt and items
        mr = MaterialReceipt.query.filter_by(release_order_id=ro.id).first()
        assert mr is not None
        assert mr.receipt_no == '16409883'
        assert len(mr.items) == 26
        
        pole_receipt_item = next((i for i in mr.items if i.material_name == 'PSC Pole 8 MTR'), None)
        assert pole_receipt_item is not None
        assert float(pole_receipt_item.qty) == 68.0
        
        # Verify farmers
        farmers = Farmer.query.filter_by(release_order_id=ro.id).all()
        assert len(farmers) == 8
        
        f1 = Farmer.query.filter_by(release_order_id=ro.id, applicant_name='CHAUDHARY HAMIRBHAI LALABHAI').first()
        assert f1 is not None
        assert f1.village == 'LODRA'
        assert float(f1.ht) == 0.148
        
        # Verify farmer materials
        m_ht = next((m for m in f1.materials if m.material_name == 'Conductor 55 mm 3wire'), None)
        assert m_ht is not None
        assert float(m_ht.qty_required) == 148.0
        
        # Clean up database entries from first WO/RO to prevent receipt number collision in step 3
        FarmerMaterial.query.delete()
        Farmer.query.delete()
        MaterialReceiptItem.query.delete()
        MaterialReceipt.query.delete()
        ReleaseOrder.query.delete()
        db.session.commit()
        
        # 3. Test direct upload via manual form
        wo2 = WorkOrder(
            work_order_no='WO-COMBINED-TEST-2',
            po_no='102600-2',
            contract_amount=Decimal('1500000.00'),
            balance_amount=Decimal('1500000.00')
        )
        db.session.add(wo2)
        db.session.commit()
        
        with open(pdf_path, 'rb') as f:
            form_data = {
                'work_order_id': wo2.id,
                'release_no': '5',
                'po_no': '102600-2',
                'release_amount': '138469.29',
                'scheme': 'DZ',
                'release_date': '2025-12-23',
                'pdf_file': (BytesIO(f.read()), 'media__1782024645219.pdf')
            }
            manual_res = client.post('/work-orders/add-release-order', data=form_data, content_type='multipart/form-data')
            
        assert manual_res.status_code == 302 # redirects to details
        
        # Verify everything was added for the manual upload too
        ro2 = ReleaseOrder.query.filter_by(work_order_id=wo2.id, release_no='5').first()
        assert ro2 is not None
        
        mr2 = MaterialReceipt.query.filter_by(release_order_id=ro2.id).first()
        assert mr2 is not None
        assert mr2.receipt_no == '16409883'
        assert len(mr2.items) == 26
        
        farmers2 = Farmer.query.filter_by(release_order_id=ro2.id).all()
        assert len(farmers2) == 8


def test_manager_dashboard_and_consumption(client):
    # Log in as admin (needs admin for debit-history access at end of test)
    login_res = login_as_admin(client)
    assert login_res.status_code == 200

    with app.app_context():
        # Setup test data
        wo = WorkOrder(
            work_order_no='WO-MGR-TEST',
            po_no='POMGR123',
            contract_amount=Decimal('500000.00'),
            balance_amount=Decimal('500000.00')
        )
        db.session.add(wo)
        db.session.commit()

        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no='1',
            po_no='POMGR123',
            release_amount=Decimal('100000.00'),
            remaining_amount=Decimal('100000.00'),
            status='Pending'
        )
        db.session.add(ro)
        db.session.commit()

        farmer = Farmer(
            release_order_id=ro.id,
            applicant_name='Farmer Ram',
            village='V1',
            sr_number='SR-MGR1',
            status='Pending'
        )
        db.session.add(farmer)
        db.session.commit()

        # Check and seed materials if they aren't seeded in database context
        pole = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not pole:
            pole = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0)
            db.session.add(pole)
        cable = Material.query.filter_by(name='Conducto 34mm 2wire').first()
        if not cable:
            cable = Material(name='Conducto 34mm 2wire', unit='Mtr', opening_stock=1000.0)
            db.session.add(cable)
        db.session.commit()

        fm1 = FarmerMaterial(
            farmer_id=farmer.id,
            material_name='PSC Pole 8 MTR',
            qty_required=Decimal('5.0'),
            qty_issued=Decimal('0.0'),
            qty_consumed=Decimal('0.0')
        )
        fm2 = FarmerMaterial(
            farmer_id=farmer.id,
            material_name='Conducto 34mm 2wire',
            qty_required=Decimal('100.0'),
            qty_issued=Decimal('0.0'),
            qty_consumed=Decimal('0.0')
        )
        db.session.add(fm1)
        db.session.add(fm2)
        db.session.commit()

        ro_id = ro.id
        farmer_id = farmer.id

    # 1. Access manager dashboard
    res = client.get('/manager')
    assert res.status_code == 200
    assert b'WO-MGR-TEST' in res.data
    assert b'Sub-WO #1' in res.data

    # 2. Update status to Active
    res = client.post(f'/manager/update-status/{ro_id}', data={'status': 'Active'}, follow_redirects=True)
    assert res.status_code == 200
    assert b'Status: Active' in res.data  # redirected to consumption details page

    # Check status in DB
    with app.app_context():
        ro_db = ReleaseOrder.query.get(ro_id)
        assert ro_db.status == 'Active'

    # 3. Save Draft Consumption
    res = client.post(f'/manager/sub-order/{ro_id}/save', data={
        'action': 'draft',
        f'consumed_{farmer_id}_PSC Pole 8 MTR': '3.0',
        f'consumed_{farmer_id}_Conducto 34mm 2wire': '50.0'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'consumption draft saved' in res.data

    # Verify db status is In Progress
    with app.app_context():
        ro_db = ReleaseOrder.query.get(ro_id)
        assert ro_db.status == 'In Progress'
        
        # Verify farmer status is Started
        f_db = Farmer.query.get(farmer_id)
        assert f_db.status == 'Started'

        # Verify quantities in FarmerMaterial
        fm1_db = FarmerMaterial.query.filter_by(farmer_id=farmer_id, material_name='PSC Pole 8 MTR').first()
        assert float(fm1_db.qty_consumed) == 3.0
        fm2_db = FarmerMaterial.query.filter_by(farmer_id=farmer_id, material_name='Conducto 34mm 2wire').first()
        assert float(fm2_db.qty_consumed) == 50.0

        # Verify central Material consumed_qty is updated (draft debits it)
        m1 = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        assert float(m1.consumed_qty) == 3.0
        m2 = Material.query.filter_by(name='Conducto 34mm 2wire').first()
        assert float(m2.consumed_qty) == 50.0

    # 4. Final Save & Submit
    res = client.post(f'/manager/sub-order/{ro_id}/save', data={
        'action': 'submit',
        f'consumed_{farmer_id}_PSC Pole 8 MTR': '4.0',
        f'consumed_{farmer_id}_Conducto 34mm 2wire': '80.0'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'consumption sheet finalized and submitted' in res.data

    # Verify db status is Completed
    with app.app_context():
        ro_db = ReleaseOrder.query.get(ro_id)
        assert ro_db.status == 'Completed'
        
        # Verify farmer status is Completed
        f_db = Farmer.query.get(farmer_id)
        assert f_db.status == 'Completed'

        # Verify quantities in FarmerMaterial
        fm1_db = FarmerMaterial.query.filter_by(farmer_id=farmer_id, material_name='PSC Pole 8 MTR').first()
        assert float(fm1_db.qty_consumed) == 4.0
        fm2_db = FarmerMaterial.query.filter_by(farmer_id=farmer_id, material_name='Conducto 34mm 2wire').first()
        assert float(fm2_db.qty_consumed) == 80.0

        # Verify central Material consumed_qty is updated (final submit debits it)
        m1 = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        assert float(m1.consumed_qty) == 4.0
        m2 = Material.query.filter_by(name='Conducto 34mm 2wire').first()
        assert float(m2.consumed_qty) == 80.0

    # 5. Verify Debit History API returns correct info
    res = client.get('/inventory/debit-history')
    assert res.status_code == 200
    res_json = res.get_json()
    assert res_json['success'] is True
    
    # Find the debit record for Farmer Ram
    debit_ram = next((d for d in res_json['debits'] if d['farmer_name'] == 'Farmer Ram'), None)
    assert debit_ram is not None
    assert debit_ram['work_order_no'] == 'WO-MGR-TEST'
    assert debit_ram['release_no'] == '1'
    
    # Check items (PSC Pole 8 MTR should have qty 4.0, Conducto 34mm 2wire should have qty 80.0)
    items = debit_ram['items']
    pole_item = next((i for i in items if i['material_name'] == 'PSC Pole 8 MTR'), None)
    assert pole_item is not None
    assert pole_item['qty'] == 4.0
    
    cable_item = next((i for i in items if i['material_name'] == 'Conducto 34mm 2wire'), None)
    assert cable_item is not None
    assert cable_item['qty'] == 80.0


def test_individual_farmer_status_flow(client):
    # Log in as admin or manager
    login_res = login_as_admin(client)
    assert login_res.status_code == 200

    with app.app_context():
        # Setup test data
        wo = WorkOrder(
            work_order_no='WO-INDIV-TEST',
            po_no='POINDIV123',
            contract_amount=Decimal('500000.00'),
            balance_amount=Decimal('500000.00')
        )
        db.session.add(wo)
        db.session.commit()

        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no='2',
            po_no='POINDIV123',
            release_amount=Decimal('100000.00'),
            remaining_amount=Decimal('100000.00'),
            status='Pending'
        )
        db.session.add(ro)
        db.session.commit()

        f1 = Farmer(
            release_order_id=ro.id,
            applicant_name='Farmer One',
            village='V1',
            sr_number='SR-IND1',
            status='Pending'
        )
        f2 = Farmer(
            release_order_id=ro.id,
            applicant_name='Farmer Two',
            village='V1',
            sr_number='SR-IND2',
            status='Pending'
        )
        db.session.add(f1)
        db.session.add(f2)
        db.session.commit()

        fm1 = FarmerMaterial(
            farmer_id=f1.id,
            material_name='PSC Pole 8 MTR',
            qty_required=Decimal('5.0'),
            qty_issued=Decimal('0.0'),
            qty_consumed=Decimal('0.0')
        )
        fm2 = FarmerMaterial(
            farmer_id=f2.id,
            material_name='PSC Pole 8 MTR',
            qty_required=Decimal('5.0'),
            qty_issued=Decimal('0.0'),
            qty_consumed=Decimal('0.0')
        )
        db.session.add(fm1)
        db.session.add(fm2)
        db.session.commit()

        ro_id = ro.id
        f1_id = f1.id
        f2_id = f2.id

    # 1. Access manager detail page: both farmers should be in top list, not bottom
    res = client.get(f'/manager/sub-order/{ro_id}')
    assert res.status_code == 200
    assert b'Farmer One' in res.data
    assert b'Farmer Two' in res.data
    assert b'farmer-row-pending' in res.data
    assert b'No Activated Farmers' in res.data
    # Bottom grid rows should not exist yet
    assert f'farmer-{f1_id}-header-row'.encode() not in res.data
    assert f'farmer-{f2_id}-header-row'.encode() not in res.data

    # 2. Activate Farmer One
    res = client.post(f'/manager/farmer-status/{f1_id}', data={'status': 'Active'}, follow_redirects=True)
    assert res.status_code == 200
    assert b'Farmer One' in res.data
    
    # 3. Verify page state: Farmer One moved to bottom grid, Farmer Two stays in top list
    assert b'Farmer Two' in res.data  # Farmer Two still in top pending list
    assert f'farmer-{f1_id}-header-row'.encode() in res.data  # Farmer One in bottom table
    assert f'farmer-{f2_id}-header-row'.encode() not in res.data  # Farmer Two not in bottom table
    
    with app.app_context():
        assert Farmer.query.get(f1_id).status == 'Active'
        assert Farmer.query.get(f2_id).status == 'Pending'

    # 4. Dispute/Reject Farmer Two
    res = client.post(f'/manager/farmer-status/{f2_id}', data={'status': 'Disputed'}, follow_redirects=True)
    assert res.status_code == 200
    assert b'Rejected' in res.data
    
    # 5. Verify page state: both farmers are now in the bottom grid, top list is empty (shows 'All farmers have been activated or rejected.')
    assert b'All farmers have been activated or rejected.' in res.data
    assert f'farmer-{f1_id}-header-row'.encode() in res.data
    assert f'farmer-{f2_id}-header-row'.encode() in res.data
    
    with app.app_context():
        assert Farmer.query.get(f1_id).status == 'Active'
        assert Farmer.query.get(f2_id).status == 'Disputed'

    # 6. Reset Farmer Two back to Pending
    res = client.post(f'/manager/farmer-status/{f2_id}', data={'status': 'Pending'}, follow_redirects=True)
    assert res.status_code == 200
    assert b'Reset to Pending' in res.data
    
    # 7. Verify page state: Farmer Two is back in the top list, only Farmer One is in the bottom grid
    assert b'Farmer Two' in res.data
    assert b'All farmers have been activated or rejected.' not in res.data
    assert f'farmer-{f1_id}-header-row'.encode() in res.data
    assert f'farmer-{f2_id}-header-row'.encode() not in res.data
    
    with app.app_context():
        assert Farmer.query.get(f1_id).status == 'Active'
        assert Farmer.query.get(f2_id).status == 'Pending'


def test_release_order_does_not_affect_inventory(client):
    login_res = login_as_admin(client)
    assert login_res.status_code == 200

    with app.app_context():
        # Setup WorkOrder
        wo = WorkOrder(
            work_order_no='WO-RO-TEST-STOCK',
            po_no='PO9988',
            contract_amount=Decimal('500000.00'),
            balance_amount=Decimal('500000.00')
        )
        db.session.add(wo)
        db.session.commit()
        
        # Capture starting received_qty of a material
        m = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        if not m:
            m = Material(name='PSC Pole 8 MTR', unit='Nos', opening_stock=100.0, received_qty=Decimal('0.0'))
            db.session.add(m)
            db.session.commit()
        starting_qty = float(m.received_qty)
        wo_id = wo.id

    # Add Release Order via OCR JSON post
    ocr_payload = {
        'work_order_id': wo_id,
        'release_no': '9',
        'po_no': 'PO9988',
        'release_amount': '10000.00',
        'remaining_amount': '10000.00',
        'scheme': 'StockTest',
        'release_date': '2026-06-21',
        'vault_doc_id': None,
        'pdf_path': None,
        'receipt_no': 'MR-RO-9-STOCK',
        'materials': [
            {
                'material_name': 'PSC Pole 8 MTR',
                'qty': 50
            }
        ],
        'farmers': []
    }
    res = client.post('/work-orders/save-release-order-ocr', json=ocr_payload)
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # 1. Verify that received_qty did NOT change
    with app.app_context():
        m_after = Material.query.filter_by(name='PSC Pole 8 MTR').first()
        assert float(m_after.received_qty) == starting_qty

    # 2. Verify that it does not show up as a credit receipt log on inventory page
    inv_res = client.get('/inventory')
    assert inv_res.status_code == 200
    assert b'MR-RO-9-STOCK' not in inv_res.data

    # 3. Verify that it does not show up in the credit history API
    history_res = client.get('/inventory/credit-history')
    assert history_res.status_code == 200
    h_data = history_res.get_json()
    assert h_data['success'] is True
    mr_exists = any(c['receipt_no'] == 'MR-RO-9-STOCK' for c in h_data['credits'])
    assert mr_exists is False

    # 4. Verify that it does not show up in the material history ledger API
    mat_history_res = client.get('/inventory/material-history/PSC Pole 8 MTR')
    m_h_data = mat_history_res.get_json()
    print("DEBUG M_H_DATA:", m_h_data)
    assert m_h_data['success'] is True
    mr_hist_exists = any('MR-RO-9-STOCK' in c['source'] for c in m_h_data['credits'])
    assert mr_hist_exists is False


def test_download_excel_flow(client):
    login_as_manager(client)
    
    with app.app_context():
        # Setup mock entities
        wo = WorkOrder(
            work_order_no='WO-EXCEL-TEST',
            po_no='POEXCEL123',
            contract_amount=Decimal('500000.00'),
            balance_amount=Decimal('500000.00'),
            contractor_name='Excel Builder Ltd'
        )
        db.session.add(wo)
        db.session.commit()

        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no='1',
            po_no='POEXCEL123',
            release_amount=Decimal('100000.00'),
            remaining_amount=Decimal('100000.00'),
            status='Pending'
        )
        db.session.add(ro)
        db.session.commit()

        f = Farmer(
            release_order_id=ro.id,
            applicant_name='Excel Farmer',
            village='ExcelVille',
            sr_number='SR-EXCEL1',
            status='Pending'
        )
        db.session.add(f)
        db.session.commit()

        # Seed material required to be consumed
        fm = FarmerMaterial(
            farmer_id=f.id,
            material_name='PSC Pole 8 MTR',
            qty_required=Decimal('5.0'),
            qty_issued=Decimal('0.0'),
            qty_consumed=Decimal('0.0')
        )
        db.session.add(fm)
        db.session.commit()

        ro_id = ro.id
        f_id = f.id

    # 1. Access detail page and verify that the Excel Download button is NOT visible (since there is a pending farmer)
    res = client.get(f'/manager/sub-order/{ro_id}')
    assert res.status_code == 200
    assert b'Generate &amp; Download Excel' not in res.data
    assert b'Generate & Download Excel' not in res.data

    # 2. Try calling download endpoint when pending farmer exists. Should redirect.
    dl_res = client.get(f'/manager/sub-order/{ro_id}/download-excel', follow_redirects=True)
    assert dl_res.status_code == 200
    assert b'Cannot generate Excel spreadsheet when there are pending farmers' in dl_res.data

    # 3. Activate the farmer
    act_res = client.post(f'/manager/farmer-status/{f_id}', data={'status': 'Active'}, follow_redirects=True)
    assert act_res.status_code == 200

    # 4. Access detail page and verify Excel Download button IS now visible
    res = client.get(f'/manager/sub-order/{ro_id}')
    assert res.status_code == 200
    assert (b'Generate &amp; Download Excel' in res.data) or (b'Generate & Download Excel' in res.data)

    # 5. Call download endpoint. Should succeed and return legacy Excel file format.
    dl_res = client.get(f'/manager/sub-order/{ro_id}/download-excel')
    assert dl_res.status_code == 200
    assert dl_res.mimetype == "application/vnd.ms-excel"
    assert "attachment" in dl_res.headers["Content-Disposition"]
    assert "Release_1_Account.xls" in dl_res.headers["Content-Disposition"]
    assert len(dl_res.data) > 0


def test_multiple_farmers_grouping_excel(client):
    login_as_manager(client)
    
    with app.app_context():
        # Setup mock entities
        wo = WorkOrder(
            work_order_no='WO-GROUPING-TEST',
            po_no='POGROUPING',
            contract_amount=Decimal('500000.00'),
            balance_amount=Decimal('500000.00'),
            contractor_name='Excel Grouping Ltd'
        )
        db.session.add(wo)
        db.session.commit()

        ro = ReleaseOrder(
            work_order_id=wo.id,
            release_no='3',
            po_no='POGROUPING',
            release_amount=Decimal('100000.00'),
            remaining_amount=Decimal('100000.00'),
            status='Pending'
        )
        db.session.add(ro)
        db.session.commit()

        # Let's add 3 farmers:
        # Farmer A: has 4 poles (req_rows = 5)
        # Farmer B: has 10 poles (req_rows = 11)
        # Farmer C: has 20 poles (req_rows = 21)
        # Since Farmer A + Farmer B = 5 + 11 = 16 <= 25, they fit on page-1.
        # But if we add Farmer C (21), 16 + 21 = 37 > 25, so Farmer C will be on page-2.
        
        f_a = Farmer(release_order_id=ro.id, applicant_name='Farmer A', village='V1', sr_number='SR-A', status='Active')
        f_b = Farmer(release_order_id=ro.id, applicant_name='Farmer B', village='V2', sr_number='SR-B', status='Active')
        f_c = Farmer(release_order_id=ro.id, applicant_name='Farmer C', village='V3', sr_number='SR-C', status='Active')
        db.session.add_all([f_a, f_b, f_c])
        db.session.commit()

        # Add poles:
        for p in range(1, 5):
            db.session.add(FarmerMaterial(farmer_id=f_a.id, material_name='PSC Pole 8 MTR', pole_no=str(p), qty_consumed=Decimal('1.0')))
        for p in range(1, 11):
            db.session.add(FarmerMaterial(farmer_id=f_b.id, material_name='PSC Pole 8 MTR', pole_no=str(p), qty_consumed=Decimal('1.0')))
        for p in range(1, 21):
            db.session.add(FarmerMaterial(farmer_id=f_c.id, material_name='PSC Pole 8 MTR', pole_no=str(p), qty_consumed=Decimal('1.0')))
        db.session.commit()
        
        ro_id = ro.id

    # Call download Excel endpoint
    dl_res = client.get(f'/manager/sub-order/{ro_id}/download-excel')
    assert dl_res.status_code == 200
    assert dl_res.mimetype == "application/vnd.ms-excel"
    
    # Read generated workbook using xlrd
    import xlrd
    wb = xlrd.open_workbook(file_contents=dl_res.data)
    sheet_names = wb.sheet_names()
    assert 'page-1' in sheet_names
    assert 'page-2' in sheet_names
    assert 'page-3' not in sheet_names # only 2 pages
    
    # Verify page-1 contents
    sheet1 = wb.sheet_by_name('page-1')
    # Row 5 should be Farmer A description
    val_5 = sheet1.cell_value(5, 2)
    assert 'Farmer A' in val_5
    
    # Row 10 should be Farmer B description
    # Farmer A occupied rows 5 (header) + 6, 7, 8, 9 (poles 1 to 4) = 5 rows.
    # So Farmer B header starts at row 10
    val_10 = sheet1.cell_value(10, 2)
    assert 'Farmer B' in val_10
    
    # Row 30 should be TOTAL, containing sum of poles (4 + 10 = 14)
    # The material is PSC Pole 8 MTR which is column 6 (0-indexed: col 6 is PSC Pole 8 MTR)
    assert sheet1.cell_value(30, 6) == 14.0
    
    # Verify page-2 contents
    sheet2 = wb.sheet_by_name('page-2')
    val2_5 = sheet2.cell_value(5, 2)
    assert 'Farmer C' in val2_5
    # Row 30 should be TOTAL for Farmer C (20 poles)
    assert sheet2.cell_value(30, 6) == 20.0
    
    # Verify SUB TOTAL sheet has the page totals
    sub_total = wb.sheet_by_name('SUB TOTAL')
    # Row 5 (Page 1) should show 14.0 in col 6
    assert sub_total.cell_value(5, 6) == 14.0
    # Row 6 (Page 2) should show 20.0 in col 6
    assert sub_total.cell_value(6, 6) == 20.0
    # Row 16 (TOTAL) should show 34.0 (14.0 + 20.0) in col 6
    assert sub_total.cell_value(16, 6) == 34.0


def test_delete_release_order(client):
    from models import WorkOrder, ReleaseOrder
    
    login_as_admin(client)
    
    # 1. Create a WorkOrder
    wo = WorkOrder(
        work_order_no='WO-DEL-TEST',
        po_no='999000',
        contract_amount=Decimal('50000.00'),
        balance_amount=Decimal('40000.00')
    )
    db.session.add(wo)
    db.session.commit()
    wo_id = wo.id
    
    # 2. Create a ReleaseOrder
    ro = ReleaseOrder(
        work_order_id=wo_id,
        release_no='1',
        po_no='999000',
        release_amount=Decimal('10000.00'),
        remaining_amount=Decimal('10000.00'),
        status='Pending'
    )
    db.session.add(ro)
    db.session.commit()
    
    ro_id = ro.id
    
    # Verify it exists in db
    assert ReleaseOrder.query.get(ro_id) is not None
    
    # 3. Call delete endpoint
    res = client.get(f'/work-orders/release-order/delete/{ro_id}')
    assert res.status_code == 302 # Redirects back to work order details page
    
    # Verify it is deleted from db
    assert ReleaseOrder.query.get(ro_id) is None
    
    # Verify WorkOrder balance amount is restored to contract_amount (40000 + 10000 = 50000)
    wo_db = WorkOrder.query.get(wo_id)
    assert wo_db.balance_amount == Decimal('50000.00')



