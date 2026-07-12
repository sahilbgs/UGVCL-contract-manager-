"""
Cleanup script to purge fake/sample farmer records and corrupted material entries from the database.
"""
from app import app
from models import db, Farmer, FarmerMaterial, MaterialReceipt, MaterialReceiptItem, ReleaseOrder

FAKE_SR_NUMBERS = [
    '12908522', '12675179', '12975610', '12808888', 
    '13596252', '13051760', '12915102', '13179579',
    '14625068', '14625069', '14625070', '14625071',
    '14625072', '14625073', '14625074', '14625075',
    '14625076', '14625077', '14625078', '14625079',
    '14625080', '14625081', '14625082', '14625083',
    '14625084', '14625085', '14625086'
]

def cleanup():
    with app.app_context():
        count = 0
        for sr in FAKE_SR_NUMBERS:
            farmers = Farmer.query.filter_by(sr_number=sr).all()
            for f in farmers:
                FarmerMaterial.query.filter_by(farmer_id=f.id).delete()
                db.session.delete(f)
                count += 1
        db.session.commit()
        print(f"Purged {count} fake farmer records from database.")

if __name__ == '__main__':
    cleanup()
