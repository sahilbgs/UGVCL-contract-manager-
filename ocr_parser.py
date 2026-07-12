"""
OCR Parser - Compatibility Shim

This module re-exports all public functions from the three specialized scanner modules:
  - work_order_scanner.py   (Work Order parsing)
  - sub_work_order_scanner.py (Sub-Work Order / Release Order / Farmer List parsing)
  - inventory_scanner.py    (Gate Pass / Material Receipt parsing)

Existing code that imports from `ocr_parser` will continue to work seamlessly.
New code should import directly from the specialized scanner modules.
"""

# --- Work Order Scanner ---
from work_order_scanner import (
    extract_text_from_pdf,
    parse_date,
    parse_decimal,
    parse_work_order_text,
    parse_work_order_pdf,
)

# --- Sub-Work Order Scanner ---
from sub_work_order_scanner import (
    extract_materials_from_text,
    parse_farmer_pdf_text,
    parse_release_order_text,
    parse_release_order_pdf,
    parse_farmer_pdf,
)

# --- Inventory / Gate Pass Scanner ---
from inventory_scanner import (
    levenshtein_distance,
    KNOWN_MATERIALS,
    clean_description,
    match_material,
    normalize_uom,
    normalize_mr_number,
    parse_gate_pass_text,
    parse_gate_pass_image,
)

# --- Document Classifier (uses all 3 models) ---
import os

def classify_document(text):
    """
    Uses all three trained ML models to classify a document.
    Returns 'work_order', 'release_order', or 'gate_pass'.
    """
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'doc_classifier.joblib')
    if os.path.exists(model_path):
        try:
            import joblib
            model = joblib.load(model_path)
            prediction = model.predict([text])[0]
            if prediction in ['work_order', 'release_order', 'gate_pass']:
                return prediction
        except Exception:
            pass

    # Rule-based fallback classifier
    text_lower = text.lower()
    if 'gate pass' in text_lower or 'mr number' in text_lower or 'material receipt' in text_lower:
        return 'gate_pass'
    if 'swo' in text_lower or 'release order' in text_lower or 'sub work order' in text_lower or 'material schedul' in text_lower:
        return 'release_order'
    if 'work order' in text_lower or 'tender' in text_lower or 'rfq' in text_lower or 'compulsory use sefty' in text_lower:
        return 'work_order'

    return 'gate_pass'
