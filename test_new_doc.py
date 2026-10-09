import sqlite3
import requests
import re

db_path = 'data/db.sqlite3'
# Get the first active user
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
user = conn.execute("SELECT * FROM users WHERE active=1 LIMIT 1").fetchone()
if not user:
    print("No active user found!")
    exit(1)

email = user['email']
# we can't easily get the plaintext password. But wait! We can bypass it by inserting a known password hash.
# Actually, I can just use a test client.
