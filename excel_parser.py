import os
import re
import pandas as pd
from datetime import datetime

def parse_farmer_excel(file_path):
    """
    Parses the uploaded farmer Excel file.
    Supports both:
    1. A simple flat Excel with headers like SR Number, Applicant Name, Village, Date, HT, LT4, LT2, TC.
    2. A complex UGVCL engineering sheet (like sample lt.xls) containing page-1, page-2 sheets, etc.
    
    Returns a list of dictionaries, each representing a farmer record with:
      - sr_number (str)
      - applicant_name (str)
      - village (str)
      - date (date or None)
      - ht (float)
      - lt4 (float)
      - lt2 (float)
      - tc (int)
      - materials (dict of material_name -> qty)
    """
    if not os.path.exists(file_path):
        print(f"Excel file not found: {file_path}")
        return []

    try:
        # Check sheet names first
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names
    except Exception as e:
        print(f"Error reading Excel file sheets: {e}")
        return []

    # Check if this is a flat sheet by looking at the first sheet's columns
    try:
        first_sheet_df = xl.parse(sheet_names[0], nrows=5)
        cols_lower = [str(c).lower().strip() for c in first_sheet_df.columns]
        
        # Check for typical flat sheet headers
        is_flat = False
        flat_mappings = {}
        
        keyword_mappings = {
            'sr_number': ['sr number', 'sr no.', 'sr_no', 'srno', 'serial'],
            'applicant_name': ['applicant name', 'applicant', 'name', 'applicant_name'],
            'village': ['village', 'town', 'village_name'],
            'date': ['date', 'created_at', 'allocation_date'],
            'ht': ['ht', 'ht line', 'ht_line', 'ht_length'],
            'lt4': ['lt4', 'lt 4', 'lt_4', 'lt 4 wire', 'lt 4wire'],
            'lt2': ['lt2', 'lt 2', 'lt_2', 'lt 2 wire', 'lt 2wire'],
            'tc': ['tc', 't/c', 'transformer', 'transformer centre']
        }
        
        # Check if we can find at least applicant and village columns
        for key, aliases in keyword_mappings.items():
            for alias in aliases:
                for col_name in first_sheet_df.columns:
                    if alias in str(col_name).lower():
                        flat_mappings[key] = col_name
                        break
                if key in flat_mappings:
                    break
        
        if 'applicant_name' in flat_mappings and 'village' in flat_mappings:
            is_flat = True
            
        if is_flat:
            print("Detected Flat Excel format")
            return parse_flat_excel(file_path, flat_mappings, sheet_names[0])
        else:
            print("Detected UGVCL Detailed Material Excel format")
            return parse_ugvcl_material_excel(file_path, sheet_names)
            
    except Exception as e:
        print(f"Error checking Excel format: {e}")
        return []

def parse_flat_excel(file_path, mappings, sheet_name):
    """Parses a simple flat Excel sheet based on identified column mappings."""
    farmers = []
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        for idx, row in df.iterrows():
            # Extract values using mappings
            applicant = str(row.get(mappings.get('applicant_name'), '')).strip()
            village = str(row.get(mappings.get('village'), '')).strip()
            
            if not applicant or pd.isnull(row.get(mappings.get('applicant_name'))):
                continue
                
            sr_val = row.get(mappings.get('sr_number'), '')
            sr_number = str(int(float(sr_val))) if pd.notnull(sr_val) and sr_val != '' else f"MAN-{idx+1}"
            
            date_val = row.get(mappings.get('date'))
            date_obj = None
            if pd.notnull(date_val):
                if isinstance(date_val, datetime):
                    date_obj = date_val.date()
                elif isinstance(date_val, str):
                    try:
                        date_obj = datetime.strptime(date_val, '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            date_obj = datetime.strptime(date_val, '%d-%m-%Y').date()
                        except ValueError:
                            pass
            
            ht = float(row.get(mappings.get('ht'), 0.0)) if pd.notnull(row.get(mappings.get('ht'))) else 0.0
            lt4 = float(row.get(mappings.get('lt4'), 0.0)) if pd.notnull(row.get(mappings.get('lt4'))) else 0.0
            lt2 = float(row.get(mappings.get('lt2'), 0.0)) if pd.notnull(row.get(mappings.get('lt2'))) else 0.0
            tc = int(row.get(mappings.get('tc'), 0)) if pd.notnull(row.get(mappings.get('tc'))) else 0
            
            # For flat sheets, we can estimate default materials based on lengths
            materials = {}
            if lt2 > 0:
                materials['Conductor 34mm 2wire'] = lt2 * 1000  # convert km to meters
                materials['PSC Pole 8 MTR'] = max(1, int(lt2 * 1000 / 40))  # approx 1 pole per 40m
            if lt4 > 0:
                materials['Conductor 34mm 4wire'] = lt4 * 1000
                materials['PSC Pole 8 MTR'] = materials.get('PSC Pole 8 MTR', 0) + max(1, int(lt4 * 1000 / 40))
            if ht > 0:
                materials['Conductor 55 mm 3wire'] = ht * 1000
                materials['PSC Pole 10 MTR'] = max(1, int(ht * 1000 / 50))  # approx 1 pole per 50m
            if tc > 0:
                materials['Transformer 25 KVA'] = tc
                materials['PSC Pole 10 MTR'] = materials.get('PSC Pole 10 MTR', 0) + (tc * 2)  # 2 poles per transformer
                
            farmers.append({
                'sr_number': sr_number,
                'applicant_name': applicant,
                'village': village,
                'date': date_obj,
                'ht': ht,
                'lt4': lt4,
                'lt2': lt2,
                'tc': tc,
                'materials': materials
            })
    except Exception as e:
        print(f"Error parsing flat Excel: {e}")
    return farmers

def parse_ugvcl_material_excel(file_path, sheet_names):
    """Parses UGVCL detailed material sheets (e.g. page-1, page-2) with sub-rows."""
    farmers = []
    
    # We parse sheets that start with 'page-'
    page_sheets = [name for name in sheet_names if name.strip().lower().startswith('page-')]
    
    for sheet in page_sheets:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
            if len(df) < 5:
                continue
                
            # Row 2 contains column headers
            headers = df.iloc[2].tolist()
            
            # Map column indices to material names or descriptors
            col_mappings = {}
            for col_idx, h in enumerate(headers):
                if pd.notnull(h) and str(h).strip() != '':
                    col_mappings[col_idx] = str(h).strip()
            
            current_farmer = None
            current_materials = {}
            
            # Iterate through rows starting from index 4 (after headers and units)
            for idx in range(4, len(df)):
                row = df.iloc[idx]
                val_sr_no = row.iloc[0]       # Column 0: Sr No.
                val_loc_or_sub = row.iloc[1]   # Column 1: From Location To / Sub span
                val_text_or_val = row.iloc[2]  # Column 2: Contains Name details for location row, or first material for subspan row
                
                # Check if it is a Location header row
                # A location row has val_sr_no (integer-like) and val_text_or_val is a string containing "SR.NO."
                is_location = False
                location_text = ""
                
                if pd.notnull(val_sr_no):
                    # Check if val_text_or_val is string containing SR.NO.
                    if isinstance(val_text_or_val, str) and "SR.NO." in val_text_or_val:
                        is_location = True
                        location_text = val_text_or_val
                    elif isinstance(val_loc_or_sub, str) and "SR.NO." in val_loc_or_sub:
                        # Sometimes shifts columns
                        is_location = True
                        location_text = val_loc_or_sub
                
                if is_location:
                    # If there was a previous farmer, save it
                    if current_farmer:
                        # Sum up HT, LT4, LT2, TC from aggregated materials
                        current_farmer['ht'] = float(current_materials.get('Conductor 55 mm 3wire', 0.0)) / 1000.0  # convert m to km
                        current_farmer['lt4'] = float(current_materials.get('Conductor 34mm  4wire', 0.0)) / 1000.0
                        current_farmer['lt2'] = float(current_materials.get('Conducto 34mm 2wire', 0.0)) / 1000.0
                        
                        # TC is count of transformers
                        tc_count = 0
                        for mat_name, qty in current_materials.items():
                            if 'transformer' in mat_name.lower() and qty > 0:
                                tc_count += int(qty)
                        current_farmer['tc'] = tc_count
                        current_farmer['materials'] = current_materials
                        farmers.append(current_farmer)
                    
                    # Parse location text e.g. "THAKOR SHIVAJI JOGJI - JUNA NESDA     SR.NO. 14625068"
                    # Pattern: <Name> - <Village> SR.NO. <Number>
                    applicant_name = "Unknown"
                    village = "Unknown"
                    sr_number = f"GEN-{len(farmers)+1}"
                    
                    # Extract SR.NO
                    sr_match = re.search(r'SR\.?\s*NO?\.?\s*(\d+)', location_text, re.IGNORECASE)
                    if sr_match:
                        sr_number = sr_match.group(1).strip()
                        
                    # Extract name and village before SR.NO
                    clean_text = re.sub(r'SR\.?\s*NO?\.?\s*\d+', '', location_text, flags=re.IGNORECASE).strip()
                    parts = clean_text.split('-')
                    if len(parts) >= 2:
                        applicant_name = parts[0].strip()
                        village = parts[1].strip()
                    else:
                        applicant_name = clean_text.strip()
                        
                    current_farmer = {
                        'sr_number': sr_number,
                        'applicant_name': applicant_name,
                        'village': village,
                        'date': None,  # date is not directly in detailed sheet page
                        'ht': 0.0,
                        'lt4': 0.0,
                        'lt2': 0.0,
                        'tc': 0,
                        'materials': {},
                        'poles': []
                    }
                    current_materials = {}
                    
                elif current_farmer and pd.notnull(val_loc_or_sub) and str(val_loc_or_sub).strip() != '':
                    # This is a sub-row detailing material quantities for the spans
                    pole_no = str(val_loc_or_sub).strip()
                    pole_materials = {}
                    for col_idx, material_name in col_mappings.items():
                        # skip first two columns (Sr No and Span No)
                        if col_idx < 2:
                            continue
                        val = row.iloc[col_idx]
                        if pd.notnull(val) and val != '' and val != 0:
                            try:
                                val_float = float(val)
                                current_materials[material_name] = current_materials.get(material_name, 0.0) + val_float
                                pole_materials[material_name] = val_float
                            except ValueError:
                                pass
                    
                    current_farmer['poles'].append({
                        'pole_no': pole_no,
                        'materials': pole_materials
                    })
            
            # Save the last farmer in the sheet
            if current_farmer:
                current_farmer['ht'] = float(current_materials.get('Conductor 55 mm 3wire', 0.0)) / 1000.0
                current_farmer['lt4'] = float(current_materials.get('Conductor 34mm  4wire', 0.0)) / 1000.0
                current_farmer['lt2'] = float(current_materials.get('Conducto 34mm 2wire', 0.0)) / 1000.0
                
                tc_count = 0
                for mat_name, qty in current_materials.items():
                    if 'transformer' in mat_name.lower() and qty > 0:
                        tc_count += int(qty)
                current_farmer['tc'] = tc_count
                current_farmer['materials'] = current_materials
                farmers.append(current_farmer)
                
        except Exception as e:
            print(f"Error parsing sheet {sheet}: {e}")
            import traceback
            traceback.print_exc()
            
    return farmers
