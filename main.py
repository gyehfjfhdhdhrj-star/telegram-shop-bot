import os
import sqlite3
import threading
import logging
import re
from datetime import datetime, timezone
from contextlib import closing

import telebot
from flask import Flask, request
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

=========================================================

CONFIG

=========================================================

Render Environment Variables မှာ သတ်မှတ်ပါ:

TELEGRAM_TOKEN = BotFather token

ADMIN_ID       = သင့် Telegram numeric user ID

ADMIN_USERNAME = @username (optional, @ မပါဘဲထည့်လည်းရ)

PUBLIC_URL     = https://your-service.onrender.com

DB_PATH        = /var/data/shop.db  (Render Persistent Disk သုံးရင်)



SECURITY: Token ကို code ထဲ မထည့်ပါနဲ့။

=========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip().lstrip("@")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
DB_PATH = os.getenv("DB_PATH", "/var/data/shop.db")

if not TELEGRAM_TOKEN:
raise RuntimeError("TELEGRAM_TOKEN environment variable မရှိပါ။")
if not ADMIN_ID:
raise RuntimeError("ADMIN_ID environment variable မရှိပါ။")

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True, num_threads=8)
app = Flask(name)

Active user flows only. Account data is stored in SQLite permanently.

user_state = {}
state_lock = threading.Lock()
db_lock = threading.Lock()

=========================================================

DATABASE

=========================================================

def ensure_db_dir():
directory = os.path.dirname(DB_PATH)
if directory:
os.makedirs(directory, exist_ok=True)

def db_connect():
ensure_db_dir()
conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
conn.row_factory = sqlite3.Row
return conn

def init_db():
with db_lock:
with closing(db_connect()) as conn:
conn.execute("""
CREATE TABLE IF NOT EXISTS accounts (
id INTEGER PRIMARY KEY AUTOINCREMENT,
title TEXT NOT NULL,
skins TEXT NOT NULL,
price INTEGER NOT NULL,
photos TEXT NOT NULL DEFAULT '',
status TEXT NOT NULL DEFAULT 'available',
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")
# Safe migrations for databases created by older bot versions.
account_columns = {
row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()
}
migrations = [
("original_price", "INTEGER"),
("sale_price", "INTEGER"),
("is_featured", "INTEGER NOT NULL DEFAULT 0"),
("seller_user_id", "INTEGER"),
("seller_username", "TEXT NOT NULL DEFAULT ''"),
("seller_payout_price", "INTEGER"),
]
for column, definition in migrations:
if column not in account_columns:
conn.execute(f"ALTER TABLE accounts ADD COLUMN {column} {definition}")
conn.execute("""
CREATE TABLE IF NOT EXISTS settings (
key TEXT PRIMARY KEY,
value TEXT NOT NULL
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS users (
user_id INTEGER PRIMARY KEY,
username TEXT NOT NULL DEFAULT '',
first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS activity (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER NOT NULL,
username TEXT NOT NULL DEFAULT '',
action TEXT NOT NULL,
details TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS seller_requests (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER NOT NULL,
username TEXT NOT NULL DEFAULT '',
error_info TEXT NOT NULL DEFAULT '',
price INTEGER NOT NULL,
photo_count INTEGER NOT NULL DEFAULT 0,
status TEXT NOT NULL DEFAULT 'pending',
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")
seller_columns = {
row["name"] for row in conn.execute("PRAGMA table_info(seller_requests)").fetchall()
}
seller_request_migrations = [
("binding_info", "TEXT NOT NULL DEFAULT ''"),
("moonton_change", "TEXT NOT NULL DEFAULT ''"),
("estimated_price", "INTEGER NOT NULL DEFAULT 0"),
("admin_payout_price", "INTEGER"),
("listing_price", "INTEGER"),
("account_id", "INTEGER"),
]
for column, definition in seller_request_migrations:
if column not in seller_columns:
conn.execute(f"ALTER TABLE seller_requests ADD COLUMN {column} {definition}")
if "photos" not in seller_columns:
conn.execute("ALTER TABLE seller_requests ADD COLUMN photos TEXT NOT NULL DEFAULT ''")
conn.commit()

def get_setting(key, default=None):
with db_lock:
with closing(db_connect()) as conn:
row = conn.execute(
"SELECT value FROM settings WHERE key = ?",
(key,)
).fetchone()
return row["value"] if row else default

def set_setting(key, value):
with db_lock:
with closing(db_connect()) as conn:
conn.execute("""
INSERT INTO settings(key, value)
VALUES(?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value
""", (key, str(value)))
conn.commit()

def next_account_number():
current = int(get_setting("account_counter", "1"))
set_setting("account_counter", current + 1)
return current

def make_account_id(number):
return f"ACC-{number:03d}"

def save_account(title, skins, price, photos, seller_user_id=None, seller_username="", original_price=None, sale_price=None, is_featured=0):
number = next_account_number()
account_id = make_account_id(number)
if original_price is None:
original_price = price

with db_lock:
    with closing(db_connect()) as conn:
        conn.execute("""
            INSERT INTO accounts(
                id, title, skins, price, photos, status,
                original_price, sale_price, is_featured,
                seller_user_id, seller_username
            ) VALUES(?, ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?)
        """, (
            number, title, skins or "", price, ",".join(photos),
            original_price, sale_price, int(is_featured),
            seller_user_id, seller_username or ""
        ))
        conn.commit()
return account_id

def row_to_account(row):
keys = row.keys()
original_price = row["original_price"] if "original_price" in keys else row["price"]
sale_price = row["sale_price"] if "sale_price" in keys else None
is_featured = int(row["is_featured"] or 0) if "is_featured" in keys else 0
effective_price = sale_price if sale_price and sale_price < row["price"] else row["price"]
try:
created_dt = datetime.fromisoformat(row["created_at"].replace(" ", "T")).replace(tzinfo=timezone.utc)
is_new = (datetime.now(timezone.utc) - created_dt).total_seconds() <= 72 * 3600
except Exception:
is_new = False
return {
"db_id": row["id"],
"id": make_account_id(row["id"]),
"title": row["title"],
"skins": row["skins"],
"price": row["price"],
"original_price": original_price,
"sale_price": sale_price,
"effective_price": effective_price,
"is_discounted": bool(sale_price and sale_price < row["price"]),
"is_featured": is_featured,
"is_new": is_new,
"photos": [x for x in row["photos"].split(",") if x],
"status": row["status"],
"seller_user_id": row["seller_user_id"] if "seller_user_id" in keys else None,
"seller_username": row["seller_username"] if "seller_username" in keys else "",
"seller_payout_price": row["seller_payout_price"] if "seller_payout_price" in keys else None,
"created_at": row["created_at"],
}

def get_account_by_text_id(account_id):
if not account_id.startswith("ACC-"):
return None
try:
number = int(account_id.replace("ACC-", ""))
except ValueError:
return None

with db_lock:
    with closing(db_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?",
            (number,)
        ).fetchone()
return row_to_account(row) if row else None

def get_available_accounts():
with db_lock:
with closing(db_connect()) as conn:
rows = conn.execute("""
SELECT * FROM accounts
WHERE status = 'available'
ORDER BY is_featured DESC, id DESC
""").fetchall()
return [row_to_account(row) for row in rows]

def get_discounted_accounts():
with db_lock:
with closing(db_connect()) as conn:
rows = conn.execute("""
SELECT * FROM accounts
WHERE status = 'available'
AND sale_price IS NOT NULL
AND sale_price > 0
AND sale_price < price
ORDER BY is_featured DESC, id DESC
""").fetchall()
return [row_to_account(row) for row in rows]

def get_admin_accounts(status=None):
with db_lock:
with closing(db_connect()) as conn:
if status:
rows = conn.execute(
"SELECT * FROM accounts WHERE status=? ORDER BY id DESC",
(status,)
).fetchall()
else:
rows = conn.execute(
"SELECT * FROM accounts ORDER BY id DESC"
).fetchall()
return [row_to_account(row) for row in rows]

def search_accounts(skin_keyword="", max_price=None):
keyword = (skin_keyword or "").strip().lower()
with db_lock:
with closing(db_connect()) as conn:
rows = conn.execute("""
SELECT * FROM accounts
WHERE status = 'available'
ORDER BY is_featured DESC, id DESC
""").fetchall()
result=[]
for row in rows:
acc=row_to_account(row)
if max_price is not None and acc["effective_price"] > max_price:
continue
if keyword:
hay=" ".join([acc["title"], acc["skins"]]).lower()
if keyword not in hay:
continue
result.append(acc)
return result

=========================================================

ANALYTICS / ACTIVITY

=========================================================

def log_user_activity(user, action, details=""):
user_id = int(user.id)
username = user.username or ""
with db_lock:
with closing(db_connect()) as conn:
conn.execute("""
INSERT INTO users(user_id, username, first_seen, last_seen)
VALUES(?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(user_id) DO UPDATE SET
