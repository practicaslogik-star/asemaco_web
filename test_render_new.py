import os
os.environ['PUBLIC_BASE_URL'] = 'http://127.0.0.1:5000'
from app import create_app
app = create_app({'TESTING': True, 'SECRET_KEY': '1234567890123456789012345678901234567890'})

with app.test_client() as client:
    with app.app_context():
        # Mock login
        with client.session_transaction() as sess:
            sess['uid'] = 1
            sess['av'] = 1
            sess['csrf'] = 'mock'
        
        response = client.get('/documents/new')
        print("Status code:", response.status_code)
        if response.status_code != 200:
            print("Error data:", response.data.decode('utf-8'))
