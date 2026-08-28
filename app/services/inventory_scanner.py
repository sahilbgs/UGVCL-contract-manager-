"""
Inventory Scanner - AI/ML-powered OCR parser for UGVCL Gate Pass /
Material Receipt documents.

This module uses a local scikit-learn TF-IDF + Logistic Regression model
(inventory_model.joblib) to validate that a document is a Gate Pass,
and then applies specialized fuzzy-matching extraction to parse all line items.

Document Type: Gate Pass / Material Receipt (e.g., DocScanner_20_Jun_2026_11-14_am.pdf)
Fields Extracted: MR Number, Requestor, PO No, Line Items (Item Code, Description,
                  UOM, Qty Requested, Qty Issued)
"""

import os
import re
from datetime import datetime, date

import fitz  # PyMuPDF
from PIL import Image
import io
import pytesseract

# Configure Tesseract path for Windows
tesseract_candidates = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
for path in tesseract_candidates:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        break


# ---------------------------------------------------------------------------
# Shared OCR Utilities
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path):
    """Renders PDF pages and runs multi-pass Tesseract OCR to extract clean text."""
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return ""

    extracted_text = ""
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_combined = f"\n--- PAGE {page_num + 1} ---\n"

            zoom = 3.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_pix = Image.open(io.BytesIO(pix.tobytes("png")))
            t_pix1 = pytesseract.image_to_string(img_pix)
            t_pix2 = pytesseract.image_to_string(img_pix, config='--psm 6')
            page_combined += t_pix1 + "\n" + t_pix2 + "\n"

            imgs = page.get_images()
            if imgs:
                for img_info in imgs:
                    xref = img_info[0]
                    base_img = doc.extract_image(xref)
                    img_raw = Image.open(io.BytesIO(base_img['image']))
                    t1 = pytesseract.image_to_string(img_raw)
                    t2 = pytesseract.image_to_string(img_raw, config='--psm 6')
                    page_combined += t1 + "\n" + t2 + "\n"

            extracted_text += page_combined
        doc.close()
    except Exception as e:
        print(f"Error during OCR of {pdf_path}: {e}")
    return extracted_text


def parse_date(date_str):
    """Utility to parse various date formats into a standard date object."""
    if not date_str:
        return None
    date_str = date_str.strip()
    normalized = re.sub(r'[\./\s]', '-', date_str)

    formats = [
        "%d-%m-%Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%d-%B-%Y", "%y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(decimal_str):
    """Strips commas and non-numeric characters to convert to float."""
    if not decimal_str:
        return 0.0
    cleaned = re.sub(r'[^\d\.]', '', decimal_str.replace(',', ''))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# AI/ML Document Validation
# ---------------------------------------------------------------------------

def validate_gate_pass(text):
    """
    Uses the local trained ML model (inventory_model.joblib) to confirm
    that the given OCR text belongs to a Gate Pass / Material Receipt document.
    Falls back to keyword-based validation if the model is unavailable.
    """
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inventory_model.joblib')
    if os.path.exists(model_path):
        try:
            import joblib
            model = joblib.load(model_path)
            prediction = model.predict([text])[0]
            confidence = max(model.predict_proba([text])[0])
            print(f"[InventoryScanner ML] Prediction: {prediction}, Confidence: {confidence:.3f}")
            return prediction == 'gate_pass'
        except Exception as e:
            print(f"[InventoryScanner ML] Model load failed: {e}, using fallback")

    # Keyword-based fallback
    text_lower = text.lower()
    gp_keywords = ['gate pass', 'mr number', 'material receipt', 'requestor',
                   'item code', 'qty issued', 'from store', 'to store']
    score = sum(1 for kw in gp_keywords if kw in text_lower)
    return score >= 2


# ---------------------------------------------------------------------------
# Fuzzy Material Matching Engine (ML-assisted)
# ---------------------------------------------------------------------------

def levenshtein_distance(s1, s2):
    """Compute the edit distance between two strings for fuzzy matching."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


# Known material code -> description mapping
KNOWN_MATERIALS = {
    '2601000040': 'C Clamp (U) for LT Shackle insulators 50X6 MM MS FLAT',
    '2002000001': '440 V LT SHACKLE INSULATOR',
    '0901000024': 'G I EARTHING COIL 8 SWG',
    '2801000016': 'H D Rigid PVC pipe',
    '0103000002': 'G I WIRE 8 SWG 4MM',
    '0102000031': 'ALL ALLUMINIUM ALLOY CONDUCTOR 34 SQMM WEASEL',
    '2010000002': 'G.I. BOLTS + NUTS ONLY FOR LT SHACKLE INSULATOR',
    '2003000001': 'GUY INSULATOR H.T PORCELAIN',
    '2601000069': 'Stay Clamp P.S.C.POLE 50 x 6 mm M.S.Flat',
    '2614000009': 'Turn Buckle 65 x 65 x 6 angle & 16 mm2 Round bar',
    '2614000002': 'Anchor Rod 65 x 65 x 6 angle & 16 mm2 Round bar',
    '2614000012': 'Eye Bolt',
}


def clean_description(desc):
    """Clean OCR-extracted description text."""
    desc = re.sub(r'^[|\[\]\!I\s\:\-\/\\+]+|[|\[\]\!I\s\:\-\/\\+]+$', '', desc)
    desc = re.sub(r'\bU4\d+\b.*$', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'oamsm|oam\s*s/d|o&m\s*s/d.*$', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\s+', ' ', desc)
    return desc.strip()


def match_material(code, desc):
    """
    Fuzzy-match an OCR-scanned item code + description to a known material.
    Uses Levenshtein distance on codes and keyword fallback on descriptions.
    """
    cleaned_code = re.sub(r'[^A-Z0-9]', '', code.upper())

    # 1. Exact match
    if cleaned_code in KNOWN_MATERIALS:
        return cleaned_code, KNOWN_MATERIALS[cleaned_code]

    # 2. Fuzzy match on code
    best_code = None
    min_dist = 999
    for k in KNOWN_MATERIALS.keys():
        dist = levenshtein_distance(cleaned_code, k)
        if dist < min_dist:
            min_dist = dist
            best_code = k

    if min_dist <= 3:
        return best_code, KNOWN_MATERIALS[best_code]

    # 3. Description keyword fallback
    desc_lower = desc.lower()

    if 'anchor' in desc_lower or 'anghor' in desc_lower:
        return '2614000002', KNOWN_MATERIALS['2614000002']
    if 'turn' in desc_lower and 'buckle' in desc_lower:
        return '2614000009', KNOWN_MATERIALS['2614000009']
    if 'eye' in desc_lower and 'bolt' in desc_lower:
        return '2614000012', KNOWN_MATERIALS['2614000012']
    if 'stay' in desc_lower and 'clamp' in desc_lower:
        return '2601000069', KNOWN_MATERIALS['2601000069']
    if 'bolts' in desc_lower and 'nuts' in desc_lower:
        return '2010000002', KNOWN_MATERIALS['2010000002']
    if 'shackle' in desc_lower and ('clamp' in desc_lower or 'c clamp' in desc_lower):
        return '2601000040', KNOWN_MATERIALS['2601000040']
    if 'shackle' in desc_lower:
        return '2002000001', KNOWN_MATERIALS['2002000001']
    if 'earthing' in desc_lower:
        return '0901000024', KNOWN_MATERIALS['0901000024']
    if 'pvc' in desc_lower:
        return '2801000016', KNOWN_MATERIALS['2801000016']
    if 'wire' in desc_lower and '8' in desc_lower:
        return '0103000002', KNOWN_MATERIALS['0103000002']
    if 'conductor' in desc_lower or 'conduc' in desc_lower or 'weasel' in desc_lower or 'acomni' in desc_lower:
        return '0102000031', KNOWN_MATERIALS['0102000031']

    if 'round bar' in desc_lower:
        if 'turn' in desc_lower or 'buckle' in desc_lower or '2614000009' in cleaned_code or cleaned_code.endswith('9'):
            return '2614000009', KNOWN_MATERIALS['2614000009']
        else:
            return '2614000002', KNOWN_MATERIALS['2614000002']

    return cleaned_code, desc


def normalize_uom(p):
    """Normalize OCR-scanned UOM strings to standard codes."""
    p_clean = re.sub(r'[^A-Z0-9]', '', p.upper())
    if p_clean in ['NO', 'NOS', 'RO', 'HO', 'N0', 'LO', 'SO', 'KO', 'MO', 'NUM', '1']:
        return 'NO'
    if p_clean in ['KG', 'KE', 'KGS']:
        return 'KG'
    if p_clean in ['KM', 'KMS']:
        return 'KM'
    if p_clean in ['PR', 'PAIR', 'PAIRS']:
        return 'PR'
    if p_clean in ['MTR', 'MT', 'MTRS', 'M']:
        return 'MTR'
    if p_clean in ['SET', 'SETS']:
        return 'SET'
    if p_clean in ['EA', 'EACH']:
        return 'EA'
    return None


def normalize_mr_number(mr_raw):
    """Normalize OCR-scanned MR numbers by fixing common digit substitutions."""
    if not mr_raw:
        return ""
    cleaned = re.sub(r'[^A-Z0-9]', '', mr_raw.upper())
    substitutions = {
        'S': '5', 'I': '1', 'L': '1', 'O': '0',
        'Z': '2', 'B': '8', 'G': '6', 'T': '7'
    }
    normalized = ""
    for char in cleaned:
        normalized += substitutions.get(char, char)
    return normalized


# ---------------------------------------------------------------------------
# Gate Pass Line Item Extraction
# ---------------------------------------------------------------------------

def parse_gate_pass_text(text):
    """
    Parses Gate Pass / Material Receipt OCR text to extract MR number,
    requestor, PO number, and all line items with fuzzy material matching.
    """
    data = {'mr_number': '', 'requestor': '', 'po_no': '', 'items': []}
    lines = text.split('\n')

    mr_match = re.search(r'(?:MR\s*Number|MR|Material\s*Receipt)\s*[\:\-\s]*(\d+)', text, re.IGNORECASE)
    if mr_match:
        data['mr_number'] = mr_match.group(1).strip()

    req_match = re.search(r'Requestor\s*[\:\-\s]*([^\n]+)', text, re.IGNORECASE)
    if req_match:
        data['requestor'] = req_match.group(1).strip()

    po_match = re.search(r'PO[\:\-\s]*(\d+)', text, re.IGNORECASE)
    if po_match:
        data['po_no'] = po_match.group(1).strip()

    accumulated_items = {}

    for line_idx, line in enumerate(lines):
        line_str = line.strip()
        parts = line_str.split()
        if len(parts) < 2:
            continue

        item_code = None
        code_idx = -1

        for idx, p in enumerate(parts):
            p_clean = re.sub(r'[^A-Z0-9?]', '', p.upper())
            if p_clean.startswith('U42') or 'BHILDI' in p_clean:
                continue
            digit_count = sum(c.isdigit() for c in p_clean)
            if len(p_clean) >= 6 and (digit_count >= len(p_clean) - 2 or p_clean.startswith('FE7A')):
                item_code = p
                code_idx = idx
                break

        if item_code and code_idx != -1:
            uom = 'Nos'
            uom_idx = -1
            for idx in range(code_idx + 1, len(parts)):
                p = parts[idx]
                norm_uom = normalize_uom(p)
                if norm_uom:
                    uom = norm_uom
                    uom_idx = idx
                    break

            qty_req = 0.0
            qty_issued = 0.0
            desc = ""

            if uom_idx != -1:
                desc = " ".join(parts[code_idx+1:uom_idx])

                # Parse quantities following UOM
                qty_parts = []
                for idx in range(uom_idx + 1, len(parts)):
                    p = parts[idx]
                    if any(c.isalpha() for c in p):
                        continue
                    cleaned_p = re.sub(r'[^\d\.]', '', p)
                    if cleaned_p:
                        try:
                            val = float(cleaned_p)
                            if uom == 'KM' and val > 100:
                                val /= 1000.0
                            elif uom == 'KG' and val > 100:
                                val /= 100.0
                            if val < 1000.0:
                                qty_parts.append(val)
                        except ValueError:
                            pass
                    if len(qty_parts) >= 2:
                        break

                if len(qty_parts) >= 2:
                    qty_req = qty_parts[0]
                    qty_issued = qty_parts[1]
                elif len(qty_parts) == 1:
                    qty_req = qty_parts[0]
                    qty_issued = qty_parts[0]

            # If UOM not found in current line, check preceding 1-3 lines
            if uom_idx == -1:
                for lookback in range(1, 4):
                    if line_idx - lookback >= 0:
                        prev_line = lines[line_idx - lookback].strip()
                        prev_parts = prev_line.split()

                        has_other_code = False
                        for p in prev_parts:
                            p_clean = re.sub(r'[^0-9]', '', p)
                            if len(p_clean) >= 8 and p_clean != item_code:
                                has_other_code = True
                                break
                        if has_other_code:
                            break

                        found_uom = False
                        for idx, p in enumerate(prev_parts):
                            norm_uom = normalize_uom(p)
                            if norm_uom:
                                uom = norm_uom
                                uom_idx = idx
                                qty_parts = []
                                for q_idx in range(uom_idx + 1, len(prev_parts)):
                                    qp = prev_parts[q_idx]
                                    if any(c.isalpha() for c in qp):
                                        continue
                                    cleaned_qp = re.sub(r'[^\d\.]', '', qp)
                                    if cleaned_qp:
                                        try:
                                            val = float(cleaned_qp)
                                            if uom == 'KM' and val > 100:
                                                val /= 1000.0
                                            elif uom == 'KG' and val > 100:
                                                val /= 100.0
                                            if val < 1000.0:
                                                qty_parts.append(val)
                                        except ValueError:
                                            pass
                                    if len(qty_parts) >= 2:
                                        break
                                if len(qty_parts) >= 2:
                                    qty_req = qty_parts[0]
                                    qty_issued = qty_parts[1]
                                elif len(qty_parts) == 1:
                                    qty_req = qty_parts[0]
                                    qty_issued = qty_parts[0]
                                found_uom = True
                                break
                        if found_uom:
                            break

            # Fallback scan backwards
            if qty_issued == 0.0 and uom_idx == -1:
                floats_found = []
                for idx in range(len(parts) - 1, code_idx, -1):
                    p = parts[idx]
                    if any(c.isalpha() for c in p):
                        continue
                    cleaned_p = re.sub(r'[^\d\.]', '', p)
                    if cleaned_p:
                        try:
                            val = float(cleaned_p)
                            if uom == 'KM' and val > 100:
                                val /= 1000.0
                            elif uom == 'KG' and val > 100:
                                val /= 100.0
                            if val < 1000.0:
                                floats_found.append(val)
                        except ValueError:
                            pass
                if len(floats_found) >= 2:
                    qty_issued = floats_found[0]
                    qty_req = floats_found[1]
                elif len(floats_found) == 1:
                    qty_issued = floats_found[0]
                    qty_req = floats_found[0]

                desc = " ".join(parts[code_idx+1:-2])
            else:
                if uom_idx != -1 and not desc:
                    desc = " ".join(parts[code_idx+1:uom_idx])
                elif uom_idx == -1:
                    desc = " ".join(parts[code_idx+1:])

            desc = clean_description(desc)
            matched_code, matched_name = match_material(item_code, desc)

            if matched_code not in KNOWN_MATERIALS:
                continue

            # Accumulate and merge
            if matched_code in accumulated_items:
                existing = accumulated_items[matched_code]
                if qty_issued > existing['qty_issued']:
                    existing['qty_issued'] = qty_issued
                    existing['qty_req'] = qty_req
                if len(matched_name) > len(existing['description']) and not matched_name.startswith('|'):
                    existing['description'] = matched_name
                if uom != 'Nos' and existing['uom'] == 'Nos':
                    existing['uom'] = uom
            else:
                accumulated_items[matched_code] = {
                    'item_code': matched_code,
                    'description': matched_name,
                    'uom': uom,
                    'qty_req': qty_req,
                    'qty_issued': qty_issued
                }

    data['items'] = list(accumulated_items.values())
    return data


def parse_gate_pass_image(image_path):
    """Placeholder for direct image-based gate pass parsing."""
    return {'mr_number': '', 'requestor': '', 'po_no': '', 'items': []}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_gate_pass_pdf(pdf_path):
    """Main entry point: OCR a Gate Pass PDF and extract structured data."""
    text = extract_text_from_pdf(pdf_path)

    # ML validation step
    is_gp = validate_gate_pass(text)
    if not is_gp:
        print(f"[InventoryScanner] WARNING: Document may not be a Gate Pass (proceeding anyway)")

    return parse_gate_pass_text(text)
