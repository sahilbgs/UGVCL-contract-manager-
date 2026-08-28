import urllib.request
try:
    response = urllib.request.urlopen('http://127.0.0.1:5000/static/sw.js')
    print("sw.js status:", response.status)
    print("sw.js content snippet:", response.read()[:100])
except Exception as e:
    print("sw.js failed:", e)
