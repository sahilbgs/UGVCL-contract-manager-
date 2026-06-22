from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='manager')

class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(50), nullable=False, index=True)
    po_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    tender_id = db.Column(db.String(50))
    rfq_no = db.Column(db.String(50))
    pr_no = db.Column(db.String(50))
    approval_no = db.Column(db.String(100))
    contract_amount = db.Column(db.Numeric(15, 2), nullable=False)
    balance_amount = db.Column(db.Numeric(15, 2), nullable=False)
    contractor_name = db.Column(db.String(150))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    pdf_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    release_orders = db.relationship('ReleaseOrder', backref='work_order', cascade='all, delete-orphan')

class ReleaseOrder(db.Model):
    __tablename__ = 'release_orders'
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    release_no = db.Column(db.String(50), nullable=False)
    release_date = db.Column(db.Date)
    po_no = db.Column(db.String(50), nullable=False, index=True)
    release_amount = db.Column(db.Numeric(15, 2), nullable=False)
    remaining_amount = db.Column(db.Numeric(15, 2))
    scheme = db.Column(db.String(50))
    pdf_path = db.Column(db.String(255))
    status = db.Column(db.String(50), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    farmers = db.relationship('Farmer', backref='release_order')
    receipts = db.relationship('MaterialReceipt', backref='release_order')
    bills = db.relationship('Bill', backref='release_order')

    @property
    def consumed_materials_summary(self):
        from collections import defaultdict
        summary = defaultdict(float)
        for farmer in self.farmers:
            for fm in farmer.materials:
                if fm.qty_consumed and fm.qty_consumed > 0:
                    summary[fm.material_name] += float(fm.qty_consumed)
        return dict(summary)

class Farmer(db.Model):
    __tablename__ = 'farmers'
    id = db.Column(db.Integer, primary_key=True)
    release_order_id = db.Column(db.Integer, db.ForeignKey('release_orders.id'), nullable=True)
    sr_number = db.Column(db.String(50), nullable=False, index=True)
    applicant_name = db.Column(db.String(150), nullable=False)
    village = db.Column(db.String(100))
    date = db.Column(db.Date)
    ht = db.Column(db.Numeric(10, 3), default=0.0)
    lt4 = db.Column(db.Numeric(10, 3), default=0.0)
    lt2 = db.Column(db.Numeric(10, 3), default=0.0)
    tc = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='Pending')  # Pending, Material Issued, Started, Completed
    po_no = db.Column(db.String(50), nullable=True)
    release_no = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    materials = db.relationship('FarmerMaterial', backref='farmer', cascade='all, delete-orphan')

    @property
    def display_po_no(self):
        if self.release_order:
            return self.release_order.po_no
        return self.po_no or 'N/A'

    @property
    def display_release_no(self):
        if self.release_order:
            return self.release_order.release_no
        return self.release_no or 'N/A'

class FarmerMaterial(db.Model):
    __tablename__ = 'farmer_materials'
    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('farmers.id'), nullable=False)
    pole_no = db.Column(db.String(50), nullable=True)
    material_name = db.Column(db.String(100), nullable=False)
    qty_required = db.Column(db.Numeric(12, 3), default=0.0)
    qty_issued = db.Column(db.Numeric(12, 3), default=0.0)
    qty_consumed = db.Column(db.Numeric(12, 3), default=0.0)


class Material(db.Model):
    __tablename__ = 'materials'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    item_code = db.Column(db.String(50), nullable=True, index=True)
    unit = db.Column(db.String(20), nullable=False)
    opening_stock = db.Column(db.Numeric(12, 3), default=0.0)
    received_qty = db.Column(db.Numeric(12, 3), default=0.0)
    issued_qty = db.Column(db.Numeric(12, 3), default=0.0)
    consumed_qty = db.Column(db.Numeric(12, 3), default=0.0)
    unit_price = db.Column(db.Numeric(12, 2), default=0.0)
    
    @property
    def current_stock(self):
        return self.opening_stock + self.received_qty - self.issued_qty - self.consumed_qty

    @property
    def latest_credit(self):
        from models import MaterialReceiptItem, MaterialReceipt, CreditReceipt
        from sqlalchemy import desc, func
        
        last_receipt_item = MaterialReceiptItem.query.join(MaterialReceipt).filter(
            MaterialReceiptItem.material_name == self.name,
            MaterialReceiptItem.qty > 0,
            MaterialReceipt.release_order_id.is_(None)
        ).order_by(desc(MaterialReceipt.date), desc(MaterialReceipt.id)).first()
        
        last_cr = CreditReceipt.query.filter_by(material_name=self.name).filter(
            CreditReceipt.qty > 0
        ).order_by(
            desc(CreditReceipt.date), desc(CreditReceipt.id)
        ).first()
        
        if last_receipt_item and last_cr:
            if last_receipt_item.receipt.date >= last_cr.date:
                qty_sum = db.session.query(func.sum(MaterialReceiptItem.qty)).filter(
                    MaterialReceiptItem.receipt_id == last_receipt_item.receipt_id,
                    MaterialReceiptItem.material_name == self.name
                ).scalar() or 0.0
                return f"+{float(qty_sum)} {self.unit} ({last_receipt_item.receipt.receipt_no}) on {last_receipt_item.receipt.date.strftime('%d-%b-%Y')}"
            else:
                return f"+{float(last_cr.qty)} {self.unit} (CR-{last_cr.cr_number}) on {last_cr.date.strftime('%d-%b-%Y')}"
        elif last_receipt_item:
            qty_sum = db.session.query(func.sum(MaterialReceiptItem.qty)).filter(
                MaterialReceiptItem.receipt_id == last_receipt_item.receipt_id,
                MaterialReceiptItem.material_name == self.name
            ).scalar() or 0.0
            return f"+{float(qty_sum)} {self.unit} ({last_receipt_item.receipt.receipt_no}) on {last_receipt_item.receipt.date.strftime('%d-%b-%Y')}"
        elif last_cr:
            return f"+{float(last_cr.qty)} {self.unit} (CR-{last_cr.cr_number}) on {last_cr.date.strftime('%d-%b-%Y')}"
        return "N/A"

    @property
    def latest_debit(self):
        from models import FarmerMaterial, Farmer
        from sqlalchemy import desc, func
        
        last_fm = FarmerMaterial.query.join(Farmer).filter(
            FarmerMaterial.material_name == self.name,
            Farmer.status.in_(['Material Issued', 'Started', 'Completed']),
            (FarmerMaterial.qty_issued > 0) | (FarmerMaterial.qty_consumed > 0)
        ).order_by(desc(Farmer.date), desc(Farmer.id)).first()
        
        if last_fm:
            farmer = last_fm.farmer
            f_date = farmer.date.strftime('%d-%b-%Y') if farmer.date else "N/A"
            qty_sum = db.session.query(func.sum(FarmerMaterial.qty_issued + FarmerMaterial.qty_consumed)).filter(
                FarmerMaterial.farmer_id == last_fm.farmer_id,
                FarmerMaterial.material_name == self.name
            ).scalar() or 0.0
            return f"-{float(qty_sum)} {self.unit} ({farmer.applicant_name}) on {f_date}"
        return "N/A"

    @property
    def latest_credit_amount(self):
        from models import MaterialReceiptItem, MaterialReceipt, CreditReceipt
        from sqlalchemy import desc, func
        
        last_receipt_item = MaterialReceiptItem.query.join(MaterialReceipt).filter(
            MaterialReceiptItem.material_name == self.name,
            MaterialReceiptItem.qty > 0,
            MaterialReceipt.release_order_id.is_(None)
        ).order_by(desc(MaterialReceipt.date), desc(MaterialReceipt.id)).first()
        
        last_cr = CreditReceipt.query.filter_by(material_name=self.name).filter(
            CreditReceipt.qty > 0
        ).order_by(
            desc(CreditReceipt.date), desc(CreditReceipt.id)
        ).first()
        
        if last_receipt_item and last_cr:
            if last_receipt_item.receipt.date >= last_cr.date:
                qty_sum = db.session.query(func.sum(MaterialReceiptItem.qty)).filter(
                    MaterialReceiptItem.receipt_id == last_receipt_item.receipt_id,
                    MaterialReceiptItem.material_name == self.name
                ).scalar() or 0.0
                return f"+{float(qty_sum)} {self.unit}"
            else:
                return f"+{float(last_cr.qty)} {self.unit}"
        elif last_receipt_item:
            qty_sum = db.session.query(func.sum(MaterialReceiptItem.qty)).filter(
                MaterialReceiptItem.receipt_id == last_receipt_item.receipt_id,
                MaterialReceiptItem.material_name == self.name
            ).scalar() or 0.0
            return f"+{float(qty_sum)} {self.unit}"
        elif last_cr:
            return f"+{float(last_cr.qty)} {self.unit}"
        return "N/A"

    @property
    def latest_debit_amount(self):
        from models import FarmerMaterial, Farmer
        from sqlalchemy import desc, func
        
        last_fm = FarmerMaterial.query.join(Farmer).filter(
            FarmerMaterial.material_name == self.name,
            Farmer.status.in_(['Material Issued', 'Started', 'Completed']),
            (FarmerMaterial.qty_issued > 0) | (FarmerMaterial.qty_consumed > 0)
        ).order_by(desc(Farmer.date), desc(Farmer.id)).first()
        
        if last_fm:
            qty_sum = db.session.query(func.sum(FarmerMaterial.qty_issued + FarmerMaterial.qty_consumed)).filter(
                FarmerMaterial.farmer_id == last_fm.farmer_id,
                FarmerMaterial.material_name == self.name
            ).scalar() or 0.0
            return f"-{float(qty_sum)} {self.unit}"
        return "N/A"

class MaterialReceipt(db.Model):
    __tablename__ = 'material_receipts'
    id = db.Column(db.Integer, primary_key=True)
    release_order_id = db.Column(db.Integer, db.ForeignKey('release_orders.id'), nullable=True)
    receipt_no = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('MaterialReceiptItem', backref='receipt', cascade='all, delete-orphan')

class MaterialReceiptItem(db.Model):
    __tablename__ = 'material_receipt_items'
    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('material_receipts.id'), nullable=False)
    material_name = db.Column(db.String(100), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    rate = db.Column(db.Numeric(12, 2), default=0.0)

class CreditReceipt(db.Model):
    __tablename__ = 'credit_receipts'
    id = db.Column(db.Integer, primary_key=True)
    cr_number = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    material_name = db.Column(db.String(100), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Bill(db.Model):
    __tablename__ = 'bills'
    id = db.Column(db.Integer, primary_key=True)
    bill_no = db.Column(db.String(50), unique=True, nullable=False)
    release_order_id = db.Column(db.Integer, db.ForeignKey('release_orders.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    gst = db.Column(db.Numeric(15, 2), nullable=False)
    net_amount = db.Column(db.Numeric(15, 2), nullable=False)
    pdf_path = db.Column(db.String(255))
    status = db.Column(db.String(50), default='Pending')  # Pending, Paid
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DocumentVault(db.Model):
    __tablename__ = 'document_vault'
    id = db.Column(db.Integer, primary_key=True)
    doc_type = db.Column(db.String(50), nullable=False)  # Main Work Order, Release Order, Farmer Excel, Material Receipt, Bill, CR, Photo
    filename = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    related_id = db.Column(db.Integer, nullable=True)  # ID of the related model (e.g. work_order_id, release_order_id)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
