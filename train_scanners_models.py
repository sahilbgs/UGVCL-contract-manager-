"""
Train Scanner Models - Trains and saves three independent local AI/ML models
for classifying UGVCL documents.

Models:
1. work_order_model.joblib     - Classifies Work Order documents
2. sub_work_order_model.joblib - Classifies Sub-Work Order / Release Order documents
3. inventory_model.joblib      - Classifies Gate Pass / Material Receipt documents

Each model uses a TF-IDF Vectorizer + Logistic Regression pipeline from scikit-learn.
"""

import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# Training Data (representative OCR text samples for each document type)
# ============================================================================

# Work Order training samples
WORK_ORDER_SAMPLES = [
    "UTTAR GUJARAT VIJ COMPANY LIMITED DIVISION OFFICE DEESA WO RFQ NO PR NO contract value Security Deposit tender rate specifications accept tender",
    "UGVCL DIVISION OFFICE DEESA UGVCL/DOD-1/AC/WO/ Date Shri contractor Name of Contractor tender value Rupees Ten Lakh Security Deposit",
    "UTTAR GUJARAT VIJ COMPANY LIMITED COMPULSORY USE SEFTY INSTRUMENTS RFQ No. 78047 circle Approval Letter contract value scope of work",
    "work order no WO-6203 purchase order PO NO 102600 tender ID 234794 contractor Dineshbhai Andabhai Patel total value Rs 1076015",
    "UGVCL DOD-1 AC WO 4490 DATE 31-12-25 Erection of HT LT Line and TC work PR No 629122 RFQ No 78047 42.50% BELOW RATE",
    "We are pleased to accept your tender rate for the above work subject to our specifications and conditions terms and conditions",
    "The Total value of this work would be Rs Up to 1076012.16 42.50% BELOW Rupees Ten Lakh Seventy Six thousand Twelve",
    "TIME LIMIT 90 DAYS Security Deposit Rs.54000 SCOPE This specification covers the subject works contract amount",
]

# Sub-Work Order / Release Order training samples
RELEASE_ORDER_SAMPLES = [
    "Uttar Gujarat Vij Company Limited UGVCL/BHD/TE/BIL DOD/AC/SWO/NO Release PO NO Date Contractor ERRECTION OF HT LT TC WORK",
    "MATERIAL SCHEDUL-A PSC.POLE 8MT U.CLAMP LT SHACKLE INSULATOR EARTHING COIL PVC REGID PIPE STAY WIRE STAY CLAMP TURN BUACLE EYE BOLT ANCHOR ROAD",
    "STATEMENT SHOWING THE DETAILS OF APPLICANTS Paid Date SR No Applicant Name Village 2 Wire LT 4 Wire LT HT Line TC Remarks",
    "Sub Work Order SWO No Release No 12 PO NO 102695 SCHEDULE-B TAPPING FROM EX.POLE HT LINE SINGLE POLE STRUCTURES 8MTR",
    "Release Date 2-Jun-26 D.A.PATEL BHILDI ERRECTION OF HT.LT.& TG WORK UNDER BHILDI SD/N SCH ND TIME LIMIT 3 Months",
    "Release Order No 5 PO NO 102600 Release Date JAN 2026 Release Amount 138469.29 Cumulative Amount 1073416.08 Remaining Amount 2699.02",
    "Applicant Name Village 2 Wire LT Mtr RABARI KHENGARBHAI MASHARUBHAI MOTA KAPRA PRAKASHBHAI MAFABHAI RABARI GHARNAL MOTI",
    "SCHEDULE-B Grand Total 115170.53 THE WORK IS TO BE CARRIED OUT AS PER SPECIFICATIONS AND TERMS AND CONDITIONS OF THE RATE CONTRACT",
]

# Gate Pass / Material Receipt training samples
GATE_PASS_SAMPLES = [
    "GATE PASS Organization U42 93040200 Deesa Division I Name of the Receiver From Store Code To Store Code Work Order Number Sub Work Order Account Code",
    "GATE PASS MR Number 16535255 Requestor Mr NAYANKUMAR HIMMATLAL PATEL PO-102695-12 ERECTION OF HT LT AND TC LINE AT BHILDI SDN",
    "Line No Item Code Item Description From Subinv Locator To Subinv Locator Lot Serial No UOM Qty Req Qty Issued Issue Date Project No",
    "2601000040 C Clamp U for LT Shackle insulators 50X6 MM MS FLAT NO 168 168 2614000009 Turn Buckle 65 x 65 x 6 angle 16 mm2 Round bar",
    "Material Receipt Gate Pass document 0901000024 G I EARTHING COIL 8 SWG 0103000002 G I WIRE 8 SWG 4MM KG 85.68",
    "0102000031 ALL ALLUMINIUM ALLOY CONDUCTOR 34 SQMM WEASEL KM 3.412 2010000002 G.I. BOLTS NUTS ONLY FOR LT SHACKLE INSULATOR NO 168",
    "2003000001 GUY INSULATOR H.T PORCELAIN NO 34 2601000069 Stay Clamp P.S.C.POLE 50 x 6 mm M.S.Flat PR 34",
    "2614000002 Anchor Rod 65 x 65 x 6 angle 16 mm2 Round bar NO 34 2614000012 Eye Bolt NO 34 MR number receipt qty issued",
]

# Full training dataset
X_train = WORK_ORDER_SAMPLES + RELEASE_ORDER_SAMPLES + GATE_PASS_SAMPLES
y_train = (
    ['work_order'] * len(WORK_ORDER_SAMPLES) +
    ['release_order'] * len(RELEASE_ORDER_SAMPLES) +
    ['gate_pass'] * len(GATE_PASS_SAMPLES)
)


def train_and_save_model(model_name, model_path):
    """Train a TF-IDF + LogisticRegression pipeline and save it."""
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(
            lowercase=True,
            stop_words='english',
            max_features=5000,
            ngram_range=(1, 2),
            sublinear_tf=True
        )),
        ('clf', LogisticRegression(
            C=1.0,
            max_iter=1000,
            solver='lbfgs',
            multi_class='multinomial'
        ))
    ])

    pipeline.fit(X_train, y_train)
    joblib.dump(pipeline, model_path)
    print(f"  [OK] {model_name} saved to: {model_path}")
    return pipeline


def test_model(model, model_name, test_texts):
    """Test a model against sample texts and print results."""
    print(f"\n  Testing {model_name}:")
    for text in test_texts:
        pred = model.predict([text])[0]
        probs = model.predict_proba([text])[0]
        classes = model.classes_
        max_conf = max(probs)
        print(f"    -> '{text[:60]}...' => {pred} ({max_conf:.3f})")


if __name__ == '__main__':
    print("=" * 70)
    print("  UGVCL Document Scanner - Training Local AI/ML Models")
    print("=" * 70)

    # 1. Work Order Model
    print("\n[1/3] Training Work Order Model...")
    wo_path = os.path.join(BASE_DIR, 'work_order_model.joblib')
    wo_model = train_and_save_model('work_order_model', wo_path)
    test_model(wo_model, "Work Order Model", [
        "UGVCL DIVISION OFFICE tender rate contract value Rs 1076015 accept your tender Security Deposit",
        "SCHEDULE-B MATERIAL SCHEDUL-A PSC POLE Applicant Name Village",
        "GATE PASS MR Number 16535255 Item Code Qty Issued"
    ])

    # 2. Sub-Work Order Model
    print("\n[2/3] Training Sub-Work Order Model...")
    swo_path = os.path.join(BASE_DIR, 'sub_work_order_model.joblib')
    swo_model = train_and_save_model('sub_work_order_model', swo_path)
    test_model(swo_model, "Sub-Work Order Model", [
        "UGVCL DIVISION OFFICE tender rate contract value Rs 1076015",
        "SWO Release No 12 PO NO 102695 MATERIAL SCHEDUL Applicant Name Village 2 Wire LT",
        "GATE PASS MR Number Item Code Description UOM Qty Issued"
    ])

    # 3. Inventory / Gate Pass Model
    print("\n[3/3] Training Inventory Model...")
    inv_path = os.path.join(BASE_DIR, 'inventory_model.joblib')
    inv_model = train_and_save_model('inventory_model', inv_path)
    test_model(inv_model, "Inventory Model", [
        "UGVCL DIVISION OFFICE tender rate contract value",
        "MATERIAL SCHEDUL PSC POLE Applicant Name Village Release No",
        "GATE PASS MR Number 16535255 Item Code 2601000040 C Clamp Qty Issued 168"
    ])

    print("\n" + "=" * 70)
    print("  All 3 models trained and saved successfully!")
    print("=" * 70)
    print(f"\n  Files created:")
    print(f"    - {wo_path}")
    print(f"    - {swo_path}")
    print(f"    - {inv_path}")
