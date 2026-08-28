import requests, re

s = requests.Session()
r = s.get('http://127.0.0.1:5000/login')
m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
csrf = m.group(1) if m else ''
print(f"CSRF found: {bool(csrf)}")

# Test login with username 'admin'
r2 = s.post('http://127.0.0.1:5000/login', 
            data={'username': 'admin', 'password': '44113290', 'csrf_token': csrf},
            allow_redirects=False)
print(f"Login admin: status={r2.status_code}, location={r2.headers.get('Location', 'N/A')}")

if r2.status_code == 302:
    r3 = s.get(r2.headers['Location'])
    print(f"Redirect target: status={r3.status_code}, url={r3.url}")
else:
    # Check if the page contains error messages
    if 'Invalid' in r2.text:
        print("LOGIN FAILED: Invalid credentials message shown")
    elif 'Login Successful' in r2.text or 'Main Inventory' in r2.text:
        print("LOGIN SUCCEEDED (no redirect, inline render)")
    else:
        # Check for flashed messages
        flash_match = re.search(r'alert-(success|danger)[^>]*>([^<]+)', r2.text)
        if flash_match:
            print(f"Flash message: category={flash_match.group(1)}, text={flash_match.group(2).strip()}")
        print(f"Response length: {len(r2.text)}")
