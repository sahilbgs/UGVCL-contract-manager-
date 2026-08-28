import requests
import re
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

s = requests.Session()

results = []

def log(test_name, status, details=""):
    ok = "PASS" if status else "FAIL"
    results.append((test_name, ok, details))
    print(f"[{ok}] {test_name}: {details}")

# Helper to extract CSRF token from HTML
def get_csrf(html):
    # Match hidden input
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'value="([^"]+)"\s*/?\s*>\s*', html)
    return None

# 1. Get login page
r = s.get('http://127.0.0.1:5000/login')
csrf = get_csrf(r.text)
log("Login Page Load", r.status_code == 200, f"status={r.status_code}, csrf_found={csrf is not None}")

# 2. Login
r = s.post('http://127.0.0.1:5000/login', 
           data={'username': 'admin', 'password': '44113290', 'csrf_token': csrf},
           allow_redirects=True)
logged_in = 'Main Inventory' in r.text or 'Dashboard' in r.text or r.url.endswith('/inventory/')
log("Admin Login", logged_in, f"final_url={r.url}, has_inventory={'Main Inventory' in r.text}")

if not logged_in:
    # Try with email
    r2 = s.get('http://127.0.0.1:5000/login')
    csrf2 = get_csrf(r2.text)
    r = s.post('http://127.0.0.1:5000/login',
               data={'username': 'admin@gmail.com', 'password': '44113290', 'csrf_token': csrf2},
               allow_redirects=True)
    logged_in = 'Main Inventory' in r.text or r.url.endswith('/inventory/')
    log("Admin Login (email)", logged_in, f"final_url={r.url}")

# Get CSRF from authenticated page
page_html = r.text
meta_csrf = re.search(r'csrf-token.*?content="([^"]*)"', page_html)
csrf_header = meta_csrf.group(1) if meta_csrf else ''

# === INVENTORY TESTS ===
print("\n--- INVENTORY SECTION ---")

# 3. Inventory page loads
r = s.get('http://127.0.0.1:5000/inventory/')
inv_ok = r.status_code == 200 and 'Stock Levels' in r.text
log("Inventory Page", inv_ok, f"status={r.status_code}, has_content={'Stock Levels' in r.text}")

# 4. Credit History API
r = s.get('http://127.0.0.1:5000/inventory/credit-history')
try:
    data = r.json()
    log("Credit History API", data.get('success', False), f"count={len(data.get('credits', []))}")
except:
    log("Credit History API", False, f"status={r.status_code}, returned HTML instead of JSON")

# 5. Debit History API
r = s.get('http://127.0.0.1:5000/inventory/debit-history')
try:
    data = r.json()
    log("Debit History API", data.get('success', False), f"count={len(data.get('debits', []))}")
except:
    log("Debit History API", False, f"status={r.status_code}, returned HTML instead of JSON")

# 6. Material History
r = s.get('http://127.0.0.1:5000/inventory/material-history/PSC%20Pole%208%20MTR')
try:
    data = r.json()
    log("Material History API", data.get('success', False), 
        f"credits={len(data.get('credits',[]))}, debits={len(data.get('debits',[]))}, ledger={len(data.get('ledger',[]))}")
except:
    log("Material History API", False, f"status={r.status_code}, returned HTML")

# 7. Check MR exists
r = s.get('http://127.0.0.1:5000/inventory/check-mr-exists/NONEXISTENT')
try:
    data = r.json()
    log("Check MR Exists API", 'exists' in data, f"exists={data.get('exists')}")
except:
    log("Check MR Exists API", False, f"status={r.status_code}")

# 8. Update Price
r = s.post('http://127.0.0.1:5000/inventory/update-price',
           json={'material_id': 1, 'price': 0},
           headers={'X-CSRFToken': csrf_header, 'X-Requested-With': 'XMLHttpRequest'})
try:
    data = r.json()
    log("Update Price API", r.status_code == 200, f"json={data}")
except:
    log("Update Price API", False, f"status={r.status_code}, text={r.text[:100]}")

# 9. Lookup Gate Pass
r = s.get('http://127.0.0.1:5000/inventory/lookup-gate-pass/TEST-123')
try:
    data = r.json()
    log("Lookup Gate Pass API", data.get('success', False), f"materials={len(data.get('all_materials', []))}")
except:
    log("Lookup Gate Pass API", False, f"status={r.status_code}")

# === WORK ORDERS TESTS ===
print("\n--- WORK ORDERS SECTION ---")

# 10. Work Orders list
r = s.get('http://127.0.0.1:5000/work-orders/')
wo_ok = r.status_code == 200 and 'Work Orders' in r.text
log("Work Orders Page", wo_ok, f"status={r.status_code}")

# 11. WO Details API
r = s.get('http://127.0.0.1:5000/work-orders/details/1')
try:
    data = r.json()
    log("WO Details API", data.get('success', False), f"ros={len(data.get('release_orders', []))}, amount={data.get('contract_amount')}")
except:
    log("WO Details API", False, f"status={r.status_code}")

# 12. WO View Page
r = s.get('http://127.0.0.1:5000/work-orders/1')
wo_view_ok = r.status_code == 200 and ('Sub-Work' in r.text or 'Release Order' in r.text or 'Work Order' in r.text)
log("WO View Page", wo_view_ok, f"status={r.status_code}, len={len(r.text)}")

# === MANAGER TESTS ===
print("\n--- MANAGER SECTION ---")

# 13. Manager Dashboard
r = s.get('http://127.0.0.1:5000/manager/')
mgr_ok = r.status_code == 200 and ('Dashboard' in r.text or 'Manager' in r.text or 'Work Order' in r.text)
log("Manager Dashboard", mgr_ok, f"status={r.status_code}, len={len(r.text)}")

# Test sub-order pages using database
from app import create_app
app = create_app()
with app.app_context():
    from app.models import ReleaseOrder, Farmer, FarmerMaterial
    
    ros = ReleaseOrder.query.all()
    print(f"\n  Found {len(ros)} Release Orders in DB")
    
    for ro in ros:
        print(f"\n  --- RO id={ro.id}, release_no={ro.release_no} ---")
        
        # 14. Sub Order Detail
        r = s.get(f'http://127.0.0.1:5000/manager/sub-order/{ro.id}')
        log(f"Sub Order Detail (RO {ro.id})", r.status_code == 200, f"status={r.status_code}, len={len(r.text)}")
        
        # 15. Active Farmers
        r = s.get(f'http://127.0.0.1:5000/manager/sub-order/{ro.id}/active-farmers')
        log(f"Active Farmers (RO {ro.id})", r.status_code == 200, f"status={r.status_code}")
        
        # 16. Download Excel
        r = s.get(f'http://127.0.0.1:5000/manager/sub-order/{ro.id}/download-excel', allow_redirects=False)
        if r.status_code == 200:
            ct = r.headers.get('Content-Type', '')
            log(f"Download Excel (RO {ro.id})", 'excel' in ct or 'spreadsheet' in ct, f"type={ct}, size={len(r.content)}")
        else:
            log(f"Download Excel (RO {ro.id})", r.status_code == 302, f"status={r.status_code} (pending farmers?)")
        
        # 17. Taping API for first farmer
        farmer = Farmer.query.filter_by(release_order_id=ro.id).first()
        if farmer:
            r = s.get(f'http://127.0.0.1:5000/manager/farmer/{farmer.id}/taping')
            try:
                data = r.json()
                log(f"GET Taping (farmer {farmer.id})", 'taping_price' in data,
                    f"price={data.get('taping_price')}, materials={len(data.get('materials', []))}")
            except:
                log(f"GET Taping (farmer {farmer.id})", False, f"status={r.status_code}")

# === AUTH TESTS ===
print("\n--- AUTH SECTION ---")

# 18. Profile page
r = s.get('http://127.0.0.1:5000/profile')
prof_ok = r.status_code == 200 and ('Profile' in r.text or 'profile' in r.text)
log("Profile Page", prof_ok, f"status={r.status_code}")

# 19. Logout
r = s.get('http://127.0.0.1:5000/logout', allow_redirects=False)
log("Logout", r.status_code in [302, 200], f"status={r.status_code}")

# === SUMMARY ===
print("\n" + "=" * 60)
print("COMPREHENSIVE ROUTE TEST SUMMARY")
print("=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"PASSED: {passed}/{len(results)}")
print(f"FAILED: {failed}/{len(results)}")
if failed > 0:
    print("\nFAILED TESTS:")
    for name, status, details in results:
        if status == "FAIL":
            print(f"  - {name}: {details}")
