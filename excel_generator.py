import xlwt
from io import BytesIO
from decimal import Decimal
from datetime import date

EXCEL_COLUMNS = [
    'Sr No.',
    'From Location To\nMR No./ Date',
    'Conducto 34mm 2wire',
    'Conductor 55 mm 3wire',
    'Conductor 34mm  4wire',
    'Conductor 34mm  5wire',
    'PSC Pole 8 MTR',
    'PSC Pole 10 MTR',
    'Three Hole Parties',
    'V-x arm',
    'Top Fitting',
    'Side Clamp',
    '11kv Comp Pin Insulator',
    '11kv Pin Insulator',
    '11kv G.I. Pin',
    '11kv Shackle Insulator',
    '11kv Shackle H/W',
    'Earthing Plate/Coil',
    'G.I. Wire 8 No.',
    'Stay Wire 7/12',
    'Stay Clamp Pair',
    'Turn Buckle',
    'Eye Bolt',
    'Stay Insulator',
    'Anchor Road',
    'C.C. Block',
    "Angle 9' Fut(65*65*6)",
    "Angle 9' Fut(50*50*6)",
    "Angle 4' Fut",
    "Angle 2'.6'' Fut",
    '11kv D.O Angle / Fuse',
    'Transformer 10 KVA',
    'Transformer 25 KVA',
    'U CLAIMP',
    'LT SHACKLE',
    'PVC PIPE',
    'L.A ',
    'MS Chanal-6 fut',
    'Bolt-2.6"(with nut)',
    'Bolt-5.0"(with nut)',
    'Bolt-7.0"(with nut)',
    'Bolt-11.0"(with nut)'
]

EXCEL_UNITS = [
    '',
    '',
    'Km',
    'Km',
    'Km',
    'Km',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'Set.',
    'No.',
    'Mt.',
    'Mt.',
    'Pair.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'Fut',
    'Fut',
    'Fut',
    'Fut',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.',
    'No.'
]

# Database material name to EXCEL_COLUMNS mapping
DB_TO_EXCEL_MAP = {
    'PSC Pole 8 MTR': 'PSC Pole 8 MTR',
    'PSC Pole 10 MTR': 'PSC Pole 10 MTR',
    'Conducto 34mm 2wire': 'Conducto 34mm 2wire',
    'Conductor 34mm  4wire': 'Conductor 34mm  4wire',
    'Conductor 55 mm 3wire': 'Conductor 55 mm 3wire',
    'Transformer 10 KVA': 'Transformer 10 KVA',
    'Transformer 25 KVA': 'Transformer 25 KVA',
    'Transformer 63 KVA': 'Transformer 25 KVA',  # Fallback map to nearest
    'Three Hole Parties': 'Three Hole Parties',
    'V-x arm': 'V-x arm',
    'Top Fitting': 'Top Fitting',
    'Side Clamp': 'Side Clamp',
    '11kv Comp Pin Insulator': '11kv Comp Pin Insulator',
    '11kv Pin Insulator': '11kv Pin Insulator',
    '11kv G.I. Pin': '11kv G.I. Pin',
    '11kv Shackle Insulator': '11kv Shackle Insulator',
    '11kv Shackle H/W': '11kv Shackle H/W',
    'Earthing Plate/Coil': 'Earthing Plate/Coil',
    'G.I. Wire 8 No.': 'G.I. Wire 8 No.',
    'Stay Wire 7/12': 'Stay Wire 7/12',
    'Stay Clamp Pair': 'Stay Clamp Pair',
    'Turn Buckle': 'Turn Buckle',
    'Eye Bolt': 'Eye Bolt',
    'Stay Insulator': 'Stay Insulator',
    'Anchor Road': 'Anchor Road',
    'C.C. Block': 'C.C. Block',
    "Angle 9' Fut(65*65*6)": "Angle 9' Fut(65*65*6)",
    "Angle 9' Fut(50*50*6)": "Angle 9' Fut(50*50*6)",
    "Angle 4' Fut": "Angle 4' Fut",
    "Angle 2'.6'' Fut": "Angle 2'.6'' Fut",
    '11kv D.O Angle / Fuse': '11kv D.O Angle / Fuse',
    'U CLAIMP': 'U CLAIMP',
    'LT SHACKLE': 'LT SHACKLE',
    'PVC PIPE': 'PVC PIPE',
    'L.A ': 'L.A ',
    'MS Chanal-6 fut': 'MS Chanal-6 fut',
    'Bolt-2.6"(with nut)': 'Bolt-2.6"(with nut)',
    'Bolt-5.0"(with nut)': 'Bolt-5.0"(with nut)',
    'Bolt-7.0"(with nut)': 'Bolt-7.0"(with nut)',
    'Bolt-11.0"(with nut)': 'Bolt-11.0"(with nut)'
}

# Column widths matching sample lt.xls (in xlwt units = 256ths of char width)
PAGE_COL_WIDTHS = {0: 2500, 1: 2500}
PAGE_COL_WIDTHS.update({col: 800 for col in range(2, 55)})

# Row heights matching sample lt.xls (in twips, 1pt = 20 twips)
PAGE_ROW_HEIGHTS = {
    0: 570, 1: 353, 2: 353, 3: 4200, 4: 518, 5: 375,
    30: 480, 32: 480,
}


def generate_release_excel(ro):
    from models import FarmerMaterial, Farmer, MaterialReceipt, MaterialReceiptItem, Material
    from sqlalchemy import func

    wb = xlwt.Workbook(encoding='utf-8')

    # =====================================================================
    # STYLES — matching sample lt.xls exactly
    # =====================================================================

    # Title: Algerian 20pt, center, no bold (Algerian is inherently decorative)
    title_style = xlwt.easyxf(
        'font: name Algerian, height 400; '
        'align: horiz center, vert center'
    )

    # Metadata labels: Iskoola Pota Bold 14pt, left or center
    meta_left_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz left, vert center'
    )
    meta_center_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz center, vert center'
    )
    meta_small_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz left, vert center'
    )
    meta_small_center_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center'
    )
    meta_right_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz right, vert center'
    )

    # Column headers: Times New Roman Bold 11pt, center, thin borders
    header_style = xlwt.easyxf(
        'font: name Times New Roman, bold on, height 220; '
        'align: horiz center, vert center, wrap on; '
        'border: left thin, right thin, top thin, bottom thin'
    )

    # Rotated column headers: Times New Roman Bold 11pt, center, thin borders, rotated 90
    header_rotated_style = xlwt.easyxf(
        'font: name Times New Roman, bold on, height 220; '
        'align: horiz center, vert center, rotation 90; '
        'border: left thin, right thin, top thin, bottom thin'
    )

    # Units row: Times New Roman Bold 10pt, center, thin borders
    unit_style = xlwt.easyxf(
        'font: name Times New Roman, bold on, height 200; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )

    # Data cells: Calibri 14pt, center, thin borders all sides
    cell_style = xlwt.easyxf(
        'font: name Calibri, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )

    # Farmer name row: Calibri 14pt, center, thin borders (NOT bold in original)
    farmer_name_style = xlwt.easyxf(
        'font: name Calibri, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )
    # Farmer index cell (left part of merge, border right=0)
    farmer_idx_left = xlwt.easyxf(
        'font: name Calibri, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right no_line, top thin, bottom thin'
    )
    farmer_idx_right = xlwt.easyxf(
        'font: name Calibri, height 280; '
        'align: horiz center, vert center; '
        'border: left no_line, right thin, top thin, bottom thin'
    )
    farmer_desc_style = xlwt.easyxf(
        'font: name Calibri, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right no_line, top thin, bottom thin'
    )

    # TOTAL row: Calibri Bold 14pt, center, thin borders
    total_style = xlwt.easyxf(
        'font: name Calibri, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )
    total_left_style = xlwt.easyxf(
        'font: name Calibri, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right no_line, top thin, bottom thin'
    )
    total_right_style = xlwt.easyxf(
        'font: name Calibri, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left no_line, right thin, top thin, bottom thin'
    )

    # Signatures: Iskoola Pota Bold 17pt
    sign_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 340; '
        'align: horiz left, vert center'
    )

    # ------ M Account specific styles ------
    # Title: Calisto MT Bold 14pt, center, medium borders top/left, double bottom
    ma_title_style = xlwt.easyxf(
        'font: name Calisto MT, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top medium, bottom double'
    )

    # M Account small center: Iskoola Pota Bold 12pt, center
    ma_small_center_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )

    # M Account meta: Iskoola Pota Bold 14pt, center, thin borders
    ma_meta_bold = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )
    ma_meta_bold_left = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    ma_meta_bold_right = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left thin, right medium, top thin, bottom thin'
    )
    # M Account smaller bold: Iskoola Pota Bold 12pt
    ma_bold_12 = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )
    ma_bold_12_left = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    ma_bold_12_right = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right medium, top thin, bottom thin'
    )
    # M Account normal 12pt
    ma_normal_12 = xlwt.easyxf(
        'font: name Iskoola Pota, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom thin'
    )
    ma_normal_12_left = xlwt.easyxf(
        'font: name Iskoola Pota, height 240; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    ma_normal_12_right = xlwt.easyxf(
        'font: name Iskoola Pota, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right medium, top thin, bottom thin'
    )
    # M Account section divider row: double bottom border
    ma_bold_12_dbl_left = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 220; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom double'
    )
    ma_bold_12_dbl = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom double'
    )
    ma_normal_12_dbl = xlwt.easyxf(
        'font: name Iskoola Pota, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right thin, top thin, bottom double'
    )
    ma_bold_12_dbl_right = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 240; '
        'align: horiz center, vert center; '
        'border: left thin, right medium, top thin, bottom double'
    )
    # M Account small 10pt (for cols 8-9 outside border area)
    ma_small_noborder = xlwt.easyxf(
        'font: name Iskoola Pota, height 200; '
        'align: horiz left, vert center'
    )
    ma_small_noborder_dbl = xlwt.easyxf(
        'font: name Iskoola Pota, height 200; '
        'align: horiz left, vert center; '
        'border: bottom double'
    )
    # M Account bold 16pt for section headers
    ma_bold_14_left = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 280; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    # M Account bold 16pt for bolt section header
    ma_bold_16_left = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 320; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    # M Account small bold for bolt row numbers
    ma_small_bold_left = xlwt.easyxf(
        'font: name Iskoola Pota, height 200; '
        'align: horiz center, vert center; '
        'border: left medium, right thin, top thin, bottom thin'
    )
    # Deputy signature style
    ma_sign_style = xlwt.easyxf(
        'font: name Iskoola Pota, bold on, height 200; '
        'align: horiz center, vert center'
    )

    # =====================================================================
    # Helper functions
    # =====================================================================

    def set_col_widths(ws, widths_dict):
        """Set column widths from a dict of col_index -> width."""
        for col_idx, width in widths_dict.items():
            ws.col(col_idx).width = width

    def set_row_heights(ws, heights_dict):
        """Set row heights from a dict of row_index -> height."""
        for row_idx, height in heights_dict.items():
            ws.row(row_idx).height_mismatch = True
            ws.row(row_idx).height = height

    # Filter out pending farmers (only show active/disputed/completed)
    active_farmers = [f for f in ro.farmers if f.status != 'Pending']

    def write_page_header(ws, page_title, page_num=None):
        """Write standard page headers matching sample lt.xls layout."""
        # Set print scaling (fit to 1 page wide, auto height)
        ws.fit_to_page = True
        ws.fit_width = 1
        ws.fit_height = 0

        # Set column widths
        set_col_widths(ws, PAGE_COL_WIDTHS)
        # Set row heights
        set_row_heights(ws, PAGE_ROW_HEIGHTS)
        # Set default row height for data rows (6-29)
        for r in range(6, 30):
            ws.row(r).height_mismatch = True
            ws.row(r).height = 360

        # Row 0: Title merged across cols 6-30
        ws.write_merge(0, 0, 6, 30, page_title, title_style)

        # Row 1: Metadata
        ws.write(1, 0, 'Name of Contractor:-', meta_left_style)
        ws.write_merge(1, 1, 6, 18, ro.work_order.contractor_name or '', meta_left_style)
        ws.write(1, 22, 'Scheme:-', meta_left_style)
        ws.write_merge(1, 1, 26, 30, getattr(ro, 'scheme', '') or '', meta_left_style)
        ws.write_merge(1, 1, 34, 37, 'PO No:-', meta_right_style)
        ws.write_merge(1, 1, 38, 41, ro.po_no or '', meta_left_style)

        # Row 2: Order details
        ws.write(2, 0, 'Annul Order No:-', meta_left_style)
        ws.write_merge(2, 2, 6, 20, ro.work_order.work_order_no or '', meta_small_center_style)
        ws.write(2, 21, 'S.W.O.No.:-', meta_left_style)
        ws.write_merge(2, 2, 25, 35, ' .....Dt-', meta_left_style)
        if page_num is not None:
            ws.write(2, 36, f'Page No-{page_num}', meta_left_style)

        # Row 3: Column headers (rotate materials, keep sr no / date horizontal)
        for col_idx, header in enumerate(EXCEL_COLUMNS):
            style = header_style if col_idx < 2 else header_rotated_style
            ws.write(3, col_idx, header, style)

        # Row 4: Units
        for col_idx, unit in enumerate(EXCEL_UNITS):
            ws.write(4, col_idx, unit, unit_style)

    # =====================================================================
    # Group Active/Disputed Farmers into Pages (max 25 rows: 5 to 29)
    # =====================================================================
    from models import db, FarmerMaterial
    import re

    def pole_sort_key(p):
        try:
            num = re.search(r'\d+', p)
            return int(num.group()) if num else 9999
        except:
            return 9999

    # Precompute poles and row requirements for each active farmer
    farmer_poles = []
    for f in active_farmers:
        poles_query = db.session.query(FarmerMaterial.pole_no).filter(
            FarmerMaterial.farmer_id == f.id,
            FarmerMaterial.pole_no.isnot(None)
        ).distinct().all()
        
        poles = sorted(list(set([p[0] for p in poles_query if p[0]])), key=pole_sort_key)
        if not poles:
            poles = ['1']
        farmer_poles.append((f, poles))

    # Group farmers into pages (up to 25 rows per page)
    pages = []
    current_page = []
    current_page_rows = 0

    for f, poles in farmer_poles:
        req_rows = 1 + len(poles) # 1 description header + N poles
        if current_page_rows + req_rows > 25:
            if current_page:
                pages.append(current_page)
            current_page = [(f, poles)]
            current_page_rows = req_rows
        else:
            current_page.append((f, poles))
            current_page_rows += req_rows

    if current_page:
        pages.append(current_page)

    page_totals = {}

    if not pages:
        # Placeholder if no active farmers
        ws = wb.add_sheet('page-1')
        write_page_header(ws, 'Inventory / Material Account Sheet', page_num=1)
        ws.write_merge(5, 5, 2, len(EXCEL_COLUMNS) - 1, 'No Activated Farmers in Sub-Work Order', farmer_desc_style)
        
        # Pad empty rows up to Row 29
        for r in range(6, 30):
            ws.write(r, 0, '', cell_style)
            ws.write(r, 1, '', cell_style)
            for col_idx in range(2, len(EXCEL_COLUMNS)):
                ws.write(r, col_idx, '', cell_style)
        
        # Row 30: TOTAL
        ws.write_merge(30, 30, 0, 1, 'TOTAL', total_left_style)
        for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
            ws.write(30, col_idx, 0.0, total_style)
            
        ws.write(32, 3, "Contractor's Sign", sign_style)
        ws.write(32, 27, "Dy.Engineer", sign_style)
    else:
        global_f_idx = 0
        for page_idx, page_farmers in enumerate(pages, 1):
            sheet_name = f'page-{page_idx}'
            ws = wb.add_sheet(sheet_name)
            write_page_header(ws, 'Inventory / Material Account Sheet', page_num=page_idx)

            row_offset = 5
            pole_col_totals = {col: 0.0 for col in EXCEL_COLUMNS[2:]}

            for f, poles in page_farmers:
                global_f_idx += 1
                
                # Write farmer info header
                status_tag = " (Disputed)" if f.status == "Disputed" else ""
                farmer_desc = f"{f.applicant_name}{status_tag} - {f.village or ''}     SR.NO. {f.sr_number or ''}"
                
                # Set farmer info row height
                ws.row(row_offset).height_mismatch = True
                ws.row(row_offset).height = 375
                
                ws.write_merge(row_offset, row_offset, 0, 1, float(global_f_idx), farmer_idx_left)
                ws.write_merge(row_offset, row_offset, 2, len(EXCEL_COLUMNS) - 1, farmer_desc, farmer_desc_style)

                is_disputed = f.status == 'Disputed'

                # Write pole rows
                for p_idx, p_name in enumerate(poles):
                    r = row_offset + 1 + p_idx
                    
                    # Set pole row height
                    ws.row(r).height_mismatch = True
                    ws.row(r).height = 360
                    
                    ws.write(r, 0, '', cell_style)
                    ws.write(r, 1, str(p_name), cell_style)

                    for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
                        val = 0.0
                        if not is_disputed:
                            db_m_names = [db_k for db_k, ex_v in DB_TO_EXCEL_MAP.items() if ex_v == col_name]
                            for db_name in db_m_names:
                                fm = FarmerMaterial.query.filter_by(farmer_id=f.id, material_name=db_name, pole_no=p_name).first()
                                if fm and fm.qty_consumed is not None:
                                    val += float(fm.qty_consumed)

                        ws.write(r, col_idx, val if val > 0 else 0.0, cell_style)
                        pole_col_totals[col_name] += val

                row_offset += 1 + len(poles)

            # Pad empty rows up to Row 29
            total_row_idx = 30
            for r in range(row_offset, total_row_idx):
                ws.write(r, 0, '', cell_style)
                ws.write(r, 1, '', cell_style)
                for col_idx in range(2, len(EXCEL_COLUMNS)):
                    ws.write(r, col_idx, '', cell_style)

            # Row 30: TOTAL — merge cols 0-1
            ws.write_merge(total_row_idx, total_row_idx, 0, 1, 'TOTAL', total_left_style)

            page_totals[page_idx] = {}
            for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
                total_val = pole_col_totals[col_name]
                ws.write(total_row_idx, col_idx, total_val, total_style)
                page_totals[page_idx][col_name] = total_val

            # Row 32: Signatures
            ws.write(32, 3, "Contractor's Sign", sign_style)
            ws.write(32, 27, "Dy.Engineer", sign_style)

    # =====================================================================
    # SUB TOTAL Sheet
    # =====================================================================
    ws_sub = wb.add_sheet('SUB TOTAL')
    write_page_header(ws_sub, 'Inventory / Material Account Sheet')

    sub_col_totals = {col: 0.0 for col in EXCEL_COLUMNS[2:]}

    # Rows 5-14: Page No:-1 through Page No:-10
    num_pages = len(pages) if pages else 1
    for page_num in range(1, 11):
        r = 4 + page_num
        ws_sub.write(r, 0, f'Page No:-{page_num}', cell_style)
        ws_sub.write(r, 1, '', cell_style)

        for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
            val = 0.0
            if pages and page_num <= len(pages):
                val = page_totals[page_num].get(col_name, 0.0)
                sub_col_totals[col_name] += val
            ws_sub.write(r, col_idx, val if val > 0 else 0.0, cell_style)

    # Row 15 empty
    for col_idx in range(len(EXCEL_COLUMNS)):
        ws_sub.write(15, col_idx, '', cell_style)

    # Row 16: TOTAL (Raw sums)
    ws_sub.write(16, 0, 'TOTAL', total_style)
    ws_sub.write(16, 1, '', total_style)
    for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
        ws_sub.write(16, col_idx, sub_col_totals[col_name], total_style)

    # Rows 17-18 empty
    for r in [17, 18]:
        for col_idx in range(len(EXCEL_COLUMNS)):
            ws_sub.write(r, col_idx, '', cell_style)

    # Precompute converted metrics
    pole_8_total = sub_col_totals.get('PSC Pole 8 MTR', 0.0)
    pole_10_total = sub_col_totals.get('PSC Pole 10 MTR', 0.0)
    t_10_total = sub_col_totals.get('Transformer 10 KVA', 0.0)
    t_25_total = sub_col_totals.get('Transformer 25 KVA', 0.0)
    transformer_total = t_10_total + t_25_total

    lt_2wire_mtr = sub_col_totals.get('Conducto 34mm 2wire', 0.0)
    lt_4wire_mtr = sub_col_totals.get('Conductor 34mm  4wire', 0.0)
    lt_2wire_conv = ((lt_2wire_mtr * 3.0) * 1.02 + (transformer_total * 15.0)) / 1000.0 if lt_2wire_mtr > 0 else 0.0
    lt_4wire_conv = ((lt_4wire_mtr * 3.0) * 1.02) / 1000.0 if lt_4wire_mtr > 0 else 0.0

    ht_total_mtr = sub_col_totals.get('Conductor 55 mm 3wire', 0.0)
    ht_conv = ((ht_total_mtr * 3.0) * 1.02) / 1000.0 if ht_total_mtr > 0 else 0.0

    gi_conv = ((pole_8_total * 10.0) + (transformer_total * 85.0) + (pole_10_total * 11.0)) * 0.102

    stay_pairs = sub_col_totals.get('Stay Clamp Pair', 0.0)
    stay_conv = (stay_pairs * 9.0) * 0.30723

    bolt_25_conv = sub_col_totals.get('Bolt-2.6"(with nut)', 0.0) * 0.154
    bolt_50_conv = sub_col_totals.get('Bolt-5.0"(with nut)', 0.0) * 0.222
    bolt_70_conv = sub_col_totals.get('Bolt-7.0"(with nut)', 0.0) * 0.326
    bolt_110_conv = sub_col_totals.get('Bolt-11.0"(with nut)', 0.0) * 0.500

    # Row 19: Converted total row
    ws_sub.write(19, 0, 'TOTAL', total_style)
    ws_sub.write(19, 1, '', total_style)

    for col_idx, col_name in enumerate(EXCEL_COLUMNS[2:], 2):
        val = sub_col_totals[col_name]
        if col_name == 'Conducto 34mm 2wire':
            val = lt_2wire_conv
        elif col_name == 'Conductor 34mm  4wire':
            val = lt_4wire_conv
        elif col_name == 'Conductor 55 mm 3wire':
            val = ht_conv
        elif col_name == 'Conductor 34mm  5wire':
            val = ''
        elif col_name == 'G.I. Wire 8 No.':
            val = gi_conv
        elif col_name == 'Stay Wire 7/12':
            val = stay_conv
        elif col_name == 'Bolt-2.6"(with nut)':
            val = bolt_25_conv
        elif col_name == 'Bolt-5.0"(with nut)':
            val = bolt_50_conv
        elif col_name == 'Bolt-7.0"(with nut)':
            val = bolt_70_conv
        elif col_name == 'Bolt-11.0"(with nut)':
            val = bolt_110_conv

        ws_sub.write(19, col_idx, val, total_style)

    # Rows 20-21 empty
    for r in [20, 21]:
        for col_idx in range(len(EXCEL_COLUMNS)):
            ws_sub.write(r, col_idx, '', cell_style)

    # Row 22: Signatures
    ws_sub.write(22, 3, "Contractor's Sign", sign_style)
    ws_sub.write(22, 27, "Dy.Engineer", sign_style)

    # =====================================================================
    # MR Sheet (Material Receipts)
    # =====================================================================
    ws_mr = wb.add_sheet('MR')
    ws_mr.fit_to_page = True
    ws_mr.fit_width = 1
    ws_mr.fit_height = 0
    set_col_widths(ws_mr, PAGE_COL_WIDTHS)
    set_row_heights(ws_mr, {0: 570, 1: 353, 2: 353, 3: 4200, 4: 518})

    # Row 0: Title
    ws_mr.write_merge(0, 0, 6, 30, 'Inventory / Material Account Sheet', title_style)

    # Row 1-2: Metadata
    ws_mr.write(1, 0, 'Name of Contractor:-', meta_left_style)
    ws_mr.write_merge(1, 1, 6, 18, ro.work_order.contractor_name or '', meta_left_style)
    ws_mr.write(2, 0, 'Annul Order No:-', meta_left_style)
    ws_mr.write_merge(2, 2, 6, 20, ro.work_order.work_order_no or '', meta_small_center_style)

    # Row 3: MR Custom Headers (rotate material columns, keep receipt meta horizontal)
    ws_mr.write(3, 0, 'From Location To\nMR No./ Date', header_style)
    ws_mr.write(3, 1, '', header_style)
    ws_mr.write(3, 2, '', header_style)
    for col_idx in range(3, len(EXCEL_COLUMNS)):
        ws_mr.write(3, col_idx, EXCEL_COLUMNS[col_idx], header_rotated_style)

    # Row 4: MR Units
    ws_mr.write(4, 0, 'MR NO', unit_style)
    ws_mr.write(4, 1, 'DATE', unit_style)
    ws_mr.write(4, 2, 'RUT', unit_style)
    for col_idx in range(3, len(EXCEL_COLUMNS)):
        ws_mr.write(4, col_idx, EXCEL_UNITS[col_idx], unit_style)

    ro_receipts = MaterialReceipt.query.filter_by(release_order_id=ro.id).all()
    mr_col_totals = {col: 0.0 for col in EXCEL_COLUMNS[3:]}

    max_mr_rows = max(20, len(ro_receipts))
    for mr_idx in range(1, max_mr_rows + 1):
        r = 4 + mr_idx
        receipt = ro_receipts[mr_idx - 1] if mr_idx <= len(ro_receipts) else None

        if receipt:
            ws_mr.write(r, 0, receipt.receipt_no, cell_style)
            ws_mr.write(r, 1, receipt.date.strftime('%d-%b-%Y') if receipt.date else '', cell_style)
        else:
            ws_mr.write(r, 0, '', cell_style)
            ws_mr.write(r, 1, '', cell_style)

        ws_mr.write(r, 2, '', cell_style)

        for col_idx in range(3, len(EXCEL_COLUMNS)):
            col_name = EXCEL_COLUMNS[col_idx]
            val = 0.0
            if receipt:
                db_m_names = [db_k for db_k, ex_v in DB_TO_EXCEL_MAP.items() if ex_v == col_name]
                for db_name in db_m_names:
                    item = MaterialReceiptItem.query.filter_by(receipt_id=receipt.id, material_name=db_name).first()
                    if item:
                        val += float(item.qty)
                if EXCEL_UNITS[col_idx] == 'Km':
                    val = val / 1000.0

            ws_mr.write(r, col_idx, val if val > 0 else 0.0, cell_style)
            if receipt:
                mr_col_totals[col_name] += val

    # Row 25: MR TOTAL
    r_total_mr = 25
    ws_mr.write(r_total_mr, 0, 'TOTAL', total_style)
    ws_mr.write(r_total_mr, 1, '', total_style)
    ws_mr.write(r_total_mr, 2, '', total_style)
    for col_idx in range(3, len(EXCEL_COLUMNS)):
        col_name = EXCEL_COLUMNS[col_idx]
        ws_mr.write(r_total_mr, col_idx, mr_col_totals[col_name], total_style)

    # Rows 26-28 empty
    for r in [26, 27, 28]:
        for col_idx in range(len(EXCEL_COLUMNS)):
            ws_mr.write(r, col_idx, '', cell_style)

    # Row 29: Signatures
    ws_mr.write(29, 3, "Contractor's Sign", sign_style)
    ws_mr.write(29, 27, "Dy.Engineer", sign_style)

    # =====================================================================
    # M Account Sheet — matching sample lt.xls formatting exactly
    # =====================================================================
    ws_ma = wb.add_sheet('M Account')
    ws_ma.fit_to_page = True
    ws_ma.fit_width = 1
    ws_ma.fit_height = 0

    # M Account column widths (12 columns)
    MA_COL_WIDTHS = {
        0: 2500, 1: 4500, 2: 2000, 3: 1500, 4: 2000,
        5: 1500, 6: 2500, 7: 1500, 8: 2500, 9: 2000,
        10: 1500, 11: 1500,
    }
    set_col_widths(ws_ma, MA_COL_WIDTHS)

    # Row 0: Title — merged cols 0-7 (matching original merge 0-8)
    ws_ma.write_merge(0, 0, 0, 7, 'MATERIAL ACCOUNT SHEET RADHANPUR-2 S/DN', ma_title_style)

    # Row 1: Metadata
    ws_ma.write_merge(1, 1, 0, 1, ro.work_order.contractor_name or '', ma_meta_bold_left)
    ws_ma.write(1, 2, 'SWO-', ma_meta_bold)
    ws_ma.write_merge(1, 1, 3, 7, ' .....Dt-', ma_meta_bold)
    ws_ma.write(1, 9, ' .....Dt-', ma_small_noborder)
    ws_ma.write(1, 10, 'Dt-', ma_small_noborder)
    ws_ma.write(1, 11, 0, ma_small_noborder)

    # Row 2: Work order / PO
    ws_ma.write_merge(2, 2, 0, 2, ro.work_order.work_order_no, ma_small_center_style)
    ws_ma.write_merge(2, 2, 4, 5, 'PONO', ma_small_center_style)
    ws_ma.write_merge(2, 2, 6, 7, ro.po_no, ma_small_center_style)

    def get_material_price(name, fallback):
        m = Material.query.filter_by(name=name).first()
        if m and m.unit_price is not None and float(m.unit_price) > 0:
            return float(m.unit_price)
        return fallback

    # === 1. G.I. Wire No. 8 Calculations ===
    # Row 3: Section header
    ws_ma.write_merge(3, 4, 0, 1, 'G.I.WIRE NO-8', ma_bold_12_left)
    ws_ma.write_merge(3, 3, 2, 5, 'TOTAL USED ', ma_bold_12)
    ws_ma.write(3, 6, gi_conv, ma_bold_12)
    ws_ma.write(3, 7, 'K.G', ma_bold_12_right)

    # Row 4: Sub-headers
    ws_ma.write(4, 2, 'NO', ma_normal_12)
    ws_ma.write(4, 3, 'WIRE', ma_normal_12)
    ws_ma.write_merge(4, 4, 4, 5, 'EXCESS', ma_normal_12)
    ws_ma.write(4, 7, 'K.G', ma_normal_12_right)

    # Row 5: PSC Pole 8 MTR earthing
    ws_ma.write(5, 0, 1.0, ma_bold_12_left)
    ws_ma.write(5, 1, 'P.S.C.POLE EIRTHING', ma_normal_12)
    ws_ma.write(5, 2, pole_8_total, ma_normal_12)
    ws_ma.write(5, 3, 'X', ma_normal_12)
    ws_ma.write(5, 4, 10.0, ma_normal_12)
    ws_ma.write(5, 5, 'MTR', ma_normal_12)
    ws_ma.write(5, 6, pole_8_total * 10.0, ma_normal_12)
    ws_ma.write(5, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(5, 8, pole_8_total, ma_small_noborder)
    ws_ma.write(5, 9, 13, ma_small_noborder)

    # Row 6: T/C earthing
    ws_ma.write(6, 0, 2.0, ma_bold_12_left)
    ws_ma.write(6, 1, 'T/C-EIRTHING', ma_normal_12)
    ws_ma.write(6, 2, transformer_total, ma_normal_12)
    ws_ma.write(6, 3, 'X', ma_normal_12)
    ws_ma.write(6, 4, 85.0, ma_normal_12)
    ws_ma.write(6, 5, 'MTR', ma_normal_12)
    ws_ma.write(6, 6, transformer_total * 85.0, ma_normal_12)
    ws_ma.write(6, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(6, 8, transformer_total, ma_small_noborder)

    # Row 7: PSC Pole 10 MTR earthing
    ws_ma.write(7, 0, 3.0, ma_bold_12_left)
    ws_ma.write(7, 1, 'P.S.C.POLE EIRTHING', ma_normal_12)
    ws_ma.write(7, 2, pole_10_total, ma_normal_12)
    ws_ma.write(7, 3, 'X', ma_normal_12)
    ws_ma.write(7, 4, 11.0, ma_normal_12)
    ws_ma.write(7, 5, 'MTR', ma_normal_12)
    ws_ma.write(7, 6, pole_10_total * 11.0, ma_normal_12)
    ws_ma.write(7, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(7, 8, pole_10_total, ma_small_noborder)
    ws_ma.write(7, 9, 13, ma_small_noborder)

    # Row 8: GI Wire summary (section divider with double bottom)
    gi_total_mtr = (pole_8_total * 10.0) + (transformer_total * 85.0) + (pole_10_total * 11.0)
    gi_total_kg = gi_total_mtr * 0.102
    ws_ma.write(8, 0, 'MTR', ma_bold_12_dbl_left)
    ws_ma.write(8, 1, gi_total_mtr, ma_bold_12_dbl)
    ws_ma.write(8, 2, 10.2, ma_normal_12_dbl)
    ws_ma.write(8, 3, 'KG', ma_normal_12_dbl)
    ws_ma.write(8, 6, gi_total_kg, ma_bold_12_dbl)
    ws_ma.write(8, 7, 'KG', ma_bold_12_dbl_right)
    ws_ma.write(8, 8, pole_8_total + transformer_total + pole_10_total, ma_small_noborder_dbl)

    # === 2. Stay Wire Section ===
    # Row 10: Section header
    ws_ma.write_merge(10, 11, 0, 1, 'STAY WIRE  7 / 12', ma_bold_12_left)
    ws_ma.write_merge(10, 11, 2, 4, 'TOTAL USED ', ma_bold_12)
    ws_ma.write_merge(10, 11, 5, 6, stay_conv, ma_bold_12)
    ws_ma.write_merge(10, 11, 7, 7, 'Kg', ma_bold_12_right)

    # Row 12: Stay set detail
    stay_pairs_total = sub_col_totals.get('Stay Clamp Pair', 0.0)
    stay_total_mtr = stay_pairs_total * 9.0
    stay_total_kg = stay_total_mtr * 0.30723
    ws_ma.write(12, 0, 1.0, ma_bold_12_left)
    ws_ma.write(12, 1, 'TOTAL STAY SET', ma_normal_12)
    ws_ma.write(12, 2, stay_pairs_total, ma_normal_12)
    ws_ma.write(12, 3, 'X', ma_normal_12)
    ws_ma.write(12, 4, 9.0, ma_normal_12)
    ws_ma.write(12, 5, 'MTR', ma_normal_12)
    ws_ma.write(12, 6, stay_total_mtr, ma_normal_12)
    ws_ma.write(12, 7, 'MTR', ma_normal_12_right)

    # Row 13: Stay summary (section divider)
    ws_ma.write(13, 0, 'Mtr', ma_bold_12_dbl_left)
    ws_ma.write(13, 1, stay_total_mtr, ma_bold_12_dbl)
    ws_ma.write(13, 2, 30.723, ma_normal_12_dbl)
    ws_ma.write(13, 3, 'KG', ma_normal_12_dbl)
    ws_ma.write(13, 6, stay_total_kg, ma_bold_12_dbl)
    ws_ma.write(13, 7, 'KG', ma_bold_12_dbl_right)

    # === 3. AAA REBBIT Conductor 34MM (LT) ===
    # Precompute conductor variables
    lt_2wire_mtr = sub_col_totals.get('Conducto 34mm 2wire', 0.0)
    lt_4wire_mtr = sub_col_totals.get('Conductor 34mm  4wire', 0.0)
    lt_total_mtr = lt_2wire_mtr + lt_4wire_mtr
    lt_stringing_mtr = lt_total_mtr * 3.0
    lt_sag_mtr = lt_stringing_mtr * 0.02
    lt_grand_total_mtr = lt_stringing_mtr + lt_sag_mtr + (transformer_total * 15.0)

    ht_total_mtr = sub_col_totals.get('Conductor 55 mm 3wire', 0.0)
    ht_stringing_mtr = ht_total_mtr * 3.0
    ht_sag_mtr = ht_stringing_mtr * 0.02
    ht_total_used_mtr = ht_stringing_mtr + ht_sag_mtr

    # Row 15: Section header
    ws_ma.write_merge(15, 16, 0, 2, 'AAA REBBITcond.34MM', ma_bold_12_left)

    # Row 17: Stringing total header
    ws_ma.write_merge(17, 17, 0, 5, 'TOTAL STRINGING OF CONDUCTOR LT', ma_bold_14_left)
    ws_ma.write(17, 6, lt_stringing_mtr / 1000.0, ma_bold_12)
    ws_ma.write(17, 7, 'KM', ma_bold_12_right)

    # Row 18: Stringing detail
    ws_ma.write(18, 0, 1.0, ma_normal_12_left)
    ws_ma.write(18, 1, 'TOTAL STRINGING OF CONDUCTOR LT', ma_normal_12)
    ws_ma.write(18, 2, lt_total_mtr, ma_normal_12)
    ws_ma.write(18, 3, 'X', ma_normal_12)
    ws_ma.write(18, 4, 3.0, ma_normal_12)
    ws_ma.write(18, 5, 'WIRE', ma_normal_12)
    ws_ma.write(18, 6, lt_stringing_mtr, ma_normal_12)
    ws_ma.write(18, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(18, 8, lt_stringing_mtr / 1000.0, ma_small_noborder)

    # Row 19: 2% Sag
    ws_ma.write(19, 0, 2.0, ma_normal_12_left)
    ws_ma.write(19, 1, '2 % SAG', ma_normal_12)
    ws_ma.write(19, 6, lt_sag_mtr, ma_normal_12)
    ws_ma.write(19, 7, 'MTR', ma_normal_12_right)

    # Row 20: TC Jumpering
    ws_ma.write(20, 0, 3.0, ma_normal_12_left)
    ws_ma.write(20, 1, 'T.C  JUMPRING', ma_normal_12)
    ws_ma.write(20, 2, transformer_total, ma_normal_12)
    ws_ma.write(20, 3, 'X', ma_normal_12)
    ws_ma.write(20, 4, 15.0, ma_normal_12)
    ws_ma.write(20, 5, 'WIRE', ma_normal_12)
    ws_ma.write(20, 6, transformer_total * 15.0, ma_normal_12)
    ws_ma.write(20, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(20, 9, lt_stringing_mtr / 1000.0, ma_small_noborder)

    # Row 21: TDP Jumpering
    ws_ma.write(21, 0, 4.0, ma_normal_12_left)
    ws_ma.write(21, 1, 'TDP  JUMPRING', ma_normal_12)
    ws_ma.write(21, 2, 0.0, ma_normal_12)
    ws_ma.write(21, 3, 'X', ma_normal_12)
    ws_ma.write(21, 4, 15.0, ma_normal_12)
    ws_ma.write(21, 5, 'WIRE', ma_normal_12)
    ws_ma.write(21, 6, 0.0, ma_normal_12)
    ws_ma.write(21, 7, 'MTR', ma_normal_12_right)

    # Row 22: SCHAL JAMPRING
    ws_ma.write(22, 0, 5.0, ma_normal_12_left)
    ws_ma.write(22, 1, 'SCHAL JAMPRING', ma_normal_12)
    ws_ma.write(22, 2, 0.0, ma_normal_12)
    ws_ma.write(22, 3, 'X', ma_normal_12)
    ws_ma.write(22, 4, 3.0, ma_normal_12)
    ws_ma.write(22, 5, 'WIRE', ma_normal_12)
    ws_ma.write(22, 6, 0.0, ma_normal_12)
    ws_ma.write(22, 7, 'MTR', ma_normal_12_right)

    # Row 23: Total Used LT
    ws_ma.write(23, 1, 'TOTAL USED', ma_bold_12)
    ws_ma.write_merge(23, 23, 2, 3, lt_grand_total_mtr / 1000.0, ma_bold_12)
    ws_ma.write_merge(23, 23, 4, 5, 'K.M.', ma_bold_12)
    ws_ma.write(23, 6, lt_grand_total_mtr, ma_normal_12)
    ws_ma.write(23, 7, 'MTR', ma_normal_12_right)

    # === 4. AAA REBBIT Conductor 55MM (HT) ===
    # Row 24: Section header
    ws_ma.write_merge(24, 25, 0, 2, 'AAA REBBITcond.55MM', ma_bold_12_left)

    # Row 26: Stringing total header
    ws_ma.write_merge(26, 26, 0, 5, 'TOTAL STRINGING OF CONDUCTOR HT', ma_bold_14_left)
    ws_ma.write(26, 6, ht_stringing_mtr / 1000.0 if ht_total_mtr > 0 else 0, ma_bold_12)
    ws_ma.write(26, 7, 'KM', ma_bold_12_right)

    # Row 27: HT stringing 2-wire
    ws_ma.write(27, 0, 1.0, ma_normal_12_left)
    ws_ma.write(27, 1, 'TOTAL STRINGING OF CONDUCTOR HT', ma_normal_12)
    ws_ma.write(27, 2, ht_total_mtr, ma_normal_12)
    ws_ma.write(27, 3, 'X', ma_normal_12)
    ws_ma.write(27, 4, 2.0, ma_normal_12)
    ws_ma.write(27, 5, 'WIRE', ma_normal_12)
    ws_ma.write(27, 6, ht_total_mtr * 2.0, ma_normal_12)
    ws_ma.write(27, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(27, 8, ht_total_mtr * 2.0 / 1000.0 if ht_total_mtr > 0 else 0, ma_small_noborder)

    # Row 28: HT stringing 3-wire
    ws_ma.write(28, 2, ht_total_mtr, ma_normal_12)
    ws_ma.write(28, 3, 'X', ma_normal_12)
    ws_ma.write(28, 4, 3.0, ma_normal_12)
    ws_ma.write(28, 5, 'WIRE', ma_normal_12)
    ws_ma.write(28, 6, ht_stringing_mtr, ma_normal_12)
    ws_ma.write(28, 7, 'MTR', ma_normal_12_right)
    ws_ma.write(28, 8, ht_stringing_mtr / 1000.0 if ht_total_mtr > 0 else 0, ma_small_noborder)

    # Row 29: 2% Sag HT
    ws_ma.write(29, 0, 2.0, ma_normal_12_left)
    ws_ma.write(29, 1, '2 % SAG', ma_normal_12)
    ws_ma.write(29, 6, ht_sag_mtr, ma_normal_12)
    ws_ma.write(29, 7, 'MTR', ma_normal_12_right)

    # Row 30: Total Used HT
    ws_ma.write_merge(30, 30, 1, 1, 'TOTAL USED', ma_bold_12)
    ws_ma.write_merge(30, 30, 2, 3, ht_total_used_mtr / 1000.0 if ht_total_mtr > 0 else 0, ma_bold_12)
    ws_ma.write_merge(30, 30, 4, 5, 'K.M.', ma_bold_12)
    ws_ma.write(30, 6, ht_total_used_mtr, ma_normal_12)
    ws_ma.write(30, 7, 'MTR', ma_normal_12_right)

    # === 5. Bolt & Nut Calculations ===
    # Row 32: Section header
    ws_ma.write_merge(32, 32, 0, 7, 'BOLT & NUT ACCOUNT SHEET', ma_bold_16_left)

    bolt_25_total = sub_col_totals.get('Bolt-2.6"(with nut)', 0.0)
    bolt_50_total = sub_col_totals.get('Bolt-5.0"(with nut)', 0.0)
    bolt_70_total = sub_col_totals.get('Bolt-7.0"(with nut)', 0.0)
    bolt_110_total = sub_col_totals.get('Bolt-11.0"(with nut)', 0.0)

    bolt_25_kg = bolt_25_total * 0.154
    bolt_50_kg = bolt_50_total * 0.222
    bolt_70_kg = bolt_70_total * 0.326
    bolt_110_kg = bolt_110_total * 0.500

    rate_25 = get_material_price('Bolt-2.6"(with nut)', 73.766)
    rate_50 = get_material_price('Bolt-5.0"(with nut)', 73.5)
    rate_70 = get_material_price('Bolt-7.0"(with nut)', 73.33)
    rate_110 = get_material_price('Bolt-11.0"(with nut)', 71.79)

    # Row 33
    ws_ma.write(33, 0, 1.0, ma_small_bold_left)
    ws_ma.write(33, 1, 'TOTAL USED BOLT 65MM( 2.5 In)', ma_normal_12)
    ws_ma.write(33, 2, bolt_25_total, ma_normal_12)
    ws_ma.write(33, 3, 'X', ma_normal_12)
    ws_ma.write_merge(33, 33, 4, 5, 0.154, ma_normal_12)
    ws_ma.write(33, 6, bolt_25_kg, ma_normal_12)
    ws_ma.write(33, 7, 'KG', ma_normal_12_right)
    ws_ma.write(33, 8, bolt_25_kg * rate_25, ma_small_noborder)
    ws_ma.write(33, 9, rate_25, ma_small_noborder)

    # Row 34
    ws_ma.write(34, 0, 2.0, ma_small_bold_left)
    ws_ma.write(34, 1, 'TOTAL USED BOLT 110MM( 5 In)', ma_normal_12)
    ws_ma.write(34, 2, bolt_50_total, ma_normal_12)
    ws_ma.write(34, 3, 'X', ma_normal_12)
    ws_ma.write_merge(34, 34, 4, 5, 0.222, ma_normal_12)
    ws_ma.write(34, 6, bolt_50_kg, ma_normal_12)
    ws_ma.write(34, 7, 'KG', ma_normal_12_right)
    ws_ma.write(34, 8, bolt_50_kg * rate_50, ma_small_noborder)
    ws_ma.write(34, 9, rate_50, ma_small_noborder)

    # Row 35
    ws_ma.write(35, 0, 3.0, ma_small_bold_left)
    ws_ma.write(35, 1, 'TOTAL USED BOLT 180MM( 7 In)', ma_normal_12)
    ws_ma.write(35, 2, bolt_70_total, ma_normal_12)
    ws_ma.write(35, 3, 'X', ma_normal_12)
    ws_ma.write_merge(35, 35, 4, 5, 0.326, ma_normal_12)
    ws_ma.write(35, 6, bolt_70_kg, ma_normal_12)
    ws_ma.write(35, 7, 'KG', ma_normal_12_right)
    ws_ma.write(35, 8, bolt_70_kg * rate_70, ma_small_noborder)
    ws_ma.write(35, 9, rate_70, ma_small_noborder)

    # Row 36
    ws_ma.write(36, 0, 4.0, ma_small_bold_left)
    ws_ma.write(36, 1, 'TOTAL USED BOLT 300MM( 11 In)', ma_normal_12)
    ws_ma.write(36, 2, bolt_110_total, ma_normal_12)
    ws_ma.write(36, 3, 'X', ma_normal_12)
    ws_ma.write_merge(36, 36, 4, 5, 0.500, ma_normal_12)
    ws_ma.write(36, 6, bolt_110_kg, ma_normal_12)
    ws_ma.write(36, 7, 'KG', ma_normal_12_right)
    ws_ma.write(36, 8, bolt_110_kg * rate_110, ma_small_noborder)
    ws_ma.write(36, 9, rate_110, ma_small_noborder)

    # Row 37: Total Used Bolts
    bolt_grand_total_kg = bolt_25_kg + bolt_50_kg + bolt_70_kg + bolt_110_kg
    ws_ma.write(37, 1, 'TOTAL USED', ma_bold_12)
    ws_ma.write_merge(37, 37, 2, 3, bolt_grand_total_kg, ma_bold_12)
    ws_ma.write_merge(37, 37, 4, 5, 'KG', ma_bold_12)

    # Row 38: Grand total amount
    bolt_grand_total_amount = (bolt_25_kg * rate_25) + (bolt_50_kg * rate_50) + (bolt_70_kg * rate_70) + (bolt_110_kg * rate_110)
    ws_ma.write(38, 8, bolt_grand_total_amount, ma_small_noborder)

    # Row 39: CGST
    cgst_amount = bolt_grand_total_amount * 0.09
    ws_ma.write(39, 8, cgst_amount, ma_small_noborder)
    ws_ma.write(39, 9, 0.09, ma_small_noborder)

    # Row 40: SGST
    sgst_amount = bolt_grand_total_amount * 0.09
    ws_ma.write(40, 8, sgst_amount, ma_small_noborder)

    # Row 42: Total & Signature
    total_amount_with_gst = bolt_grand_total_amount + cgst_amount + sgst_amount
    ws_ma.write(42, 4, 'Deputy Engr,UGVCL', ma_sign_style)
    ws_ma.write(42, 8, total_amount_with_gst, ma_small_noborder)

    # =====================================================================
    # Save to BytesIO
    # =====================================================================
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
