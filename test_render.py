import requests

s = requests.Session()
r = s.get('http://127.0.0.1:5000/login')
print('Login page:', r.status_code)

# We can't easily login without knowing an active user email/password.
# Let's write a small flask script to just render the template.
