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

# =========================================================
# CONFIG
# =========================================================
# Render Environment Variables မှာ သတ်မှတ်ပါ:
# TELEGRAM_TOKEN = BotFather token
# ADMIN_ID       = သင့် Telegram numeric user ID
# ADMIN_USERNAME = @username (optional, @ မပါဘဲထည့်လည်းရ)
# PUBLIC_URL     = https://your-service.onrender.com
# DB_PATH        = /var/data/shop.db  (Render Persistent Disk သုံးရင်)
#
# SECURITY: Token ကို code ထဲ မထည့်ပါနဲ့။
# =========================================================

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
app = Flask(__name__)

# Active user flows only. Account data is stored in SQLite permanently.
user_state = {}
state_lock = threading.Lock()
db_lock = threading.Lock()


# =========================================================
# DATABASE
# =========================================================

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


# =========================================================
# ANALYTICS / ACTIVITY
# =========================================================

def log_user_activity(user, action, details=""):
    user_id = int(user.id)
    username = user.username or ""
    with db_lock:
        with closing(db_connect()) as conn:
            conn.execute("""
                INSERT INTO users(user_id, username, first_seen, last_seen)
                VALUES(?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    last_seen=CURRENT_TIMESTAMP
            """, (user_id, username))
            conn.execute("""
                INSERT INTO activity(user_id, username, action, details)
                VALUES(?, ?, ?, ?)
            """, (user_id, username, action, details))
            conn.commit()


def record_seller_request(user_id, username, error_info, price, photo_count):
    with db_lock:
        with closing(db_connect()) as conn:
            cur = conn.execute("""
                INSERT INTO seller_requests(
                    user_id, username, error_info, price, photo_count, status
                ) VALUES(?, ?, ?, ?, ?, 'pending')
            """, (user_id, username, error_info, price, photo_count))
            conn.commit()
            return cur.lastrowid


def admin_analysis_text():
    with db_lock:
        with closing(db_connect()) as conn:
            total_users = conn.execute(
                "SELECT COUNT(*) AS n FROM users"
            ).fetchone()["n"]
            active_24h = conn.execute("""
                SELECT COUNT(*) AS n FROM users
                WHERE last_seen >= datetime('now', '-1 day')
            """).fetchone()["n"]
            total_events = conn.execute(
                "SELECT COUNT(*) AS n FROM activity"
            ).fetchone()["n"]
            pending_sellers = conn.execute("""
                SELECT COUNT(*) AS n FROM seller_requests
                WHERE status='pending'
            """).fetchone()["n"]
            accepted_sellers = conn.execute("""
                SELECT COUNT(*) AS n FROM seller_requests
                WHERE status='accepted'
            """).fetchone()["n"]
            stock = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE status='available'").fetchone()["n"]
            reserved = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE status='reserved'").fetchone()["n"]
            sold = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE status='sold'").fetchone()["n"]
            discounted = conn.execute("""SELECT COUNT(*) AS n FROM accounts WHERE status='available' AND sale_price IS NOT NULL AND sale_price < price""").fetchone()["n"]
    return (
        "📊 <b>BOT ANALYSIS</b>\n\n"
        f"👥 Bot သုံးဖူးသူ — <b>{total_users:,}</b> ယောက်\n"
        f"🟢 24 နာရီအတွင်း Active — <b>{active_24h:,}</b> ယောက်\n"
        f"🧾 Activity စုစုပေါင်း — <b>{total_events:,}</b> ကြိမ်\n"
        f"📦 Available — <b>{stock:,}</b> ခု\n"
        f"🟡 Reserved — <b>{reserved:,}</b> ခု\n"
        f"🔴 Sold — <b>{sold:,}</b> ခု\n"
        f"💸 Discounted — <b>{discounted:,}</b> ခု\n"
        f"⏳ Seller Pending — <b>{pending_sellers:,}</b> ယောက်\n"
        f"✅ Seller Accepted — <b>{accepted_sellers:,}</b> ယောက်"
    )


def seller_analysis_text():
    with db_lock:
        with closing(db_connect()) as conn:
            rows = conn.execute("""
                SELECT username, user_id, price, photo_count, status, created_at
                FROM seller_requests
                ORDER BY id DESC
                LIMIT 15
            """).fetchall()
    if not rows:
        return "💰 <b>SELLER ANALYSIS</b>\n\nလက်ရှိ Seller record မရှိသေးပါ။"
    lines = ["💰 <b>SELLER ANALYSIS</b>\n"]
    for i, r in enumerate(rows, 1):
        name = f"@{r['username']}" if r["username"] else f"ID {r['user_id']}"
        lines.append(
            f"{i}. {name} — {r['price']:,} MMK — "
            f"{r['photo_count']} ပုံ — {r['status']}"
        )
    return "\n".join(lines)


def recent_activity_text():
    with db_lock:
        with closing(db_connect()) as conn:
            rows = conn.execute("""
                SELECT username, user_id, action, details, created_at
                FROM activity
                ORDER BY id DESC
                LIMIT 20
            """).fetchall()
    if not rows:
        return "🕒 <b>RECENT ACTIVITY</b>\n\nActivity မရှိသေးပါ။"
    lines = ["🕒 <b>RECENT ACTIVITY</b>\n"]
    for r in rows:
        name = f"@{r['username']}" if r["username"] else f"ID {r['user_id']}"
        extra = f" — {r['details']}" if r["details"] else ""
        lines.append(f"• {name} — {r['action']}{extra}")
    return "\n".join(lines)


# =========================================================
# UI HELPERS
# =========================================================

def main_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မယ်", callback_data="buy_menu"),
        InlineKeyboardButton("👀 အကောင့်ကြည့်မယ်", callback_data="browse_0"),
        InlineKeyboardButton("💸 လျော့စျေးအကောင့်များ", callback_data="discount_menu"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမယ်", callback_data="sell_start"),
        InlineKeyboardButton("💡 Tips", callback_data="tips_menu"),
    )
    return markup


def back_button():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်မည် 🏠", callback_data="home")
    )
    return markup


def buy_menu_keyboard():
    # Kept for compatibility with older callback messages.
    # New users now get a single text-input buy flow.
    return None


def budget_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💵 50,000", callback_data="budget_50000"),
        InlineKeyboardButton("💵 100,000", callback_data="budget_100000"),
        InlineKeyboardButton("💵 200,000", callback_data="budget_200000"),
        InlineKeyboardButton("💵 300,000", callback_data="budget_300000"),
        InlineKeyboardButton("⌨️ Budget ကို ကိုယ်တိုင်ရိုက်မယ်", callback_data="budget_custom"),
        InlineKeyboardButton("🔙 Skin Menu", callback_data="buy_menu"),
    )
    return markup


def tips_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for i, title in enumerate([
        "🔐 Account လုံခြုံရေး",
        "📧 Email / Password",
        "🛡️ 2-Step Verification",
        "💳 ငွေပေးချေမှု သတိပြုရန်",
        "⚠️ Scam မဖြစ်အောင် သတိထားရန်",
    ], start=1):
        markup.add(InlineKeyboardButton(title, callback_data=f"tip_{i}"))
    markup.add(
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်မည် 🏠", callback_data="home")
    )
    return markup


def admin_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ အကောင့်တင်မယ်", callback_data="admin_add"),
        InlineKeyboardButton("📦 Account Manage", callback_data="admin_list"),
        InlineKeyboardButton("💰 Seller Requests", callback_data="seller_requests"),
        InlineKeyboardButton("💸 လျော့စျေးတင်မယ်", callback_data="admin_discount_list"),
        InlineKeyboardButton("📊 Bot Analysis", callback_data="admin_analysis"),
        InlineKeyboardButton("💰 Seller Analysis", callback_data="seller_analysis"),
        InlineKeyboardButton("🕒 Recent Activity", callback_data="recent_activity"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="home"),
    )
    return markup


def set_state(user_id, state):
    with state_lock:
        user_state[user_id] = state


def get_state(user_id):
    with state_lock:
        return user_state.get(user_id, {})


def clear_state(user_id):
    with state_lock:
        user_state.pop(user_id, None)


def set_search_skin(user_id, skin):
    state = get_state(user_id).copy()
    state["skin"] = skin
    set_state(user_id, state)


def set_search_budget(user_id, budget):
    state = get_state(user_id).copy()
    state["budget"] = budget
    set_state(user_id, state)


def format_account(acc):
    status_map = {
        "available": "🟢 AVAILABLE",
        "reserved": "🟡 RESERVED",
        "sold": "🔴 SOLD",
        "hidden": "⚫ HIDDEN",
    }
    lines = [
        f"🆔 <b>{acc['id']}</b>",
        f"🎮 <b>ML Account</b>",
        f"📌 {status_map.get(acc['status'], acc['status'].upper())}",
    ]
    if acc.get("is_new"):
        lines.append("🆕 <b>NEW</b>")
    if acc.get("is_featured"):
        lines.append("⭐ <b>FEATURED</b>")
    if acc.get("is_discounted"):
        lines.append(
            f"💸 <s>{acc['price']:,} MMK</s> → <b>{acc['effective_price']:,} MMK</b>"
        )
    else:
        lines.append(f"💰 <b>{acc['effective_price']:,} MMK</b>")
    return "\n".join(lines)


def account_action_keyboard(acc, admin=False, include_menu=True):
    markup = InlineKeyboardMarkup(row_width=2)
    if admin:
        markup.add(
            InlineKeyboardButton("🟢 Available", callback_data=f"status_available_{acc['id']}"),
            InlineKeyboardButton("🟡 Reserve", callback_data=f"status_reserved_{acc['id']}"),
            InlineKeyboardButton("🔴 Sold", callback_data=f"status_sold_{acc['id']}"),
            InlineKeyboardButton("⚫ Hide", callback_data=f"status_hidden_{acc['id']}"),
            InlineKeyboardButton("💸 လျော့စျေး", callback_data=f"discount_{acc['id']}"),
            InlineKeyboardButton("⭐ Featured", callback_data=f"featured_{acc['id']}"),
        )
    else:
        if acc["status"] == "available":
            markup.add(InlineKeyboardButton("🛒 ဒီအကောင့် ဝယ်မယ်", callback_data=f"buy_confirm_{acc['id']}"))
    if include_menu:
        markup.add(InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home"))
    return markup


def send_photo_batches(chat_id, photos, batch_size=10):
    photos=[p for p in photos if p]
    for i in range(0,len(photos),batch_size):
        batch=photos[i:i+batch_size]
        if len(batch)==1:
            bot.send_photo(chat_id,batch[0])
        else:
            bot.send_media_group(chat_id,[InputMediaPhoto(p) for p in batch])


def send_account_photos(chat_id, acc, include_menu=True):
    photos = acc["photos"][:15]
    if photos:
        try:
            send_photo_batches(chat_id, photos, 10)
        except Exception:
            logging.exception("Could not send account photo group for %s", acc["id"])
    bot.send_message(
        chat_id,
        format_account(acc),
        parse_mode="HTML",
        reply_markup=account_action_keyboard(acc, admin=False, include_menu=include_menu)
    )


def send_search_results(chat_id, results):
    if not results:
        bot.send_message(chat_id, "❌ ကိုက်ညီတဲ့ Account မတွေ့ပါသေးပါ။", reply_markup=back_button())
        return
    bot.send_message(chat_id, f"🎯 Account <b>{len(results)}</b> ခု တွေ့ပါပြီ။", parse_mode="HTML")
    for acc in results[:15]:
        send_account_photos(chat_id, acc, include_menu=False)


# =========================================================
# HOME
# =========================================================

@app.route("/", methods=["GET"])
def health():
    return "Gaming Shop Bot is running! OK", 200


@app.route("/health", methods=["GET"])
def health2():
    return "OK", 200


@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    # Return immediately so Telegram does not wait for handlers.
    if request.is_json:
        try:
            update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
            threading.Thread(
                target=bot.process_new_updates,
                args=([update],),
                daemon=True
            ).start()
        except Exception:
            logging.exception("Webhook update error")
    return "OK", 200


@bot.message_handler(commands=["start"])
def start_command(message):
    clear_state(message.from_user.id)
    log_user_activity(message.from_user, "start")
    text = (
        "👋 မင်္ဂလာပါ 🎮 <b>Gaming Shop Bot</b> မှ ကြိုဆိုပါတယ်။\n\n"
        "အောက်က Menu ကနေ လိုချင်တာကို ရွေးနိုင်ပါတယ်။\n"
        "🛒 ဝယ်ရန် | 👀 ကြည့်ရန် | 💰 ရောင်းရန် | 💡 Tips"
    )
    bot.send_message(
        message.chat.id,
        text,
        parse_mode="HTML",
        reply_markup=main_menu(message.from_user.id)
    )


@bot.message_handler(commands=["admin"])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    clear_state(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "👑 <b>ADMIN PANEL</b>\n\nလိုအပ်တာကို ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "home")
def callback_home(call):
    bot.answer_callback_query(call.id)
    clear_state(call.from_user.id)
    bot.send_message(
        call.message.chat.id,
        "🏠 <b>ပင်မ Menu</b>",
        parse_mode="HTML",
        reply_markup=main_menu(call.from_user.id)
    )


# =========================================================
# BUY MENU
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "buy_menu")
def buy_menu(call):
    bot.answer_callback_query(call.id)
    clear_state(call.from_user.id)
    log_user_activity(call.from_user, "buy_menu")
    bot.send_message(
        call.message.chat.id,
        "🛒 <b>အကောင့်ဝယ်မယ်</b>\n\n"
        "လိုချင်တဲ့ Skin နာမည်နဲ့ Budget ကို တစ်ကြောင်းတည်း ရိုက်ပို့ပါ။\n\n"
        "ဥပမာ — <code>Gusion | 200000</code>\n"
        "သို့မဟုတ် <code>Any | 300000</code>\n\n"
        "မရှာချင်ရင် 👀 အကောင့်ကြည့်မယ်ကနေ အားလုံးကြည့်နိုင်ပါတယ်။",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 အကောင့်အားလုံးကြည့်မယ်", callback_data="browse_0")],
            [InlineKeyboardButton("💸 လျော့စျေးအကောင့်များ", callback_data="discount_menu")],
            [InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")]
        ])
    )
    set_state(call.from_user.id, {"flow": "buy_query"})

@bot.callback_query_handler(func=lambda c: c.data == "buy_all_skin")
def buy_all_skin(call):
    bot.answer_callback_query(call.id)
    set_search_skin(call.from_user.id, "")
    bot.send_message(
        call.message.chat.id,
        "🌈 <b>အကုန်လုံးကြည့်မယ်</b> ကို ရွေးထားပါတယ်။\n\n"
        "💰 အခု Budget ကို ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=budget_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("skin_") and c.data != "skin_custom")
def buy_skin_choice(call):
    bot.answer_callback_query(call.id)
    skin = call.data.replace("skin_", "", 1)
    set_search_skin(call.from_user.id, skin)
    bot.send_message(
        call.message.chat.id,
        f"✨ Skin = <b>{skin}</b>\n\n💰 Budget ကို ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=budget_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "skin_custom")
def buy_skin_custom(call):
    bot.answer_callback_query(call.id)
    set_state(call.from_user.id, {"flow": "buy_skin_custom"})
    msg = bot.send_message(
        call.message.chat.id,
        "⌨️ <b>ကိုယ်လိုချင်တဲ့ Skin နာမည်</b> ကို ဒီမှာ ရိုက်ထည့်ပါ။\n\n"
        "ဥပမာ: Gusion, Collector, Alucard",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    bot.register_next_step_handler(msg, receive_custom_skin)


def receive_custom_skin(message):
    user_id = message.from_user.id
    if not message.text:
        bot.send_message(user_id, "⚠️ Skin နာမည်ကို စာသားနဲ့ ရိုက်ပေးပါ။")
        return

    skin = message.text.strip()
    set_search_skin(user_id, skin)

    bot.send_message(
        user_id,
        f"✅ Skin = <b>{skin}</b>\n\n💰 Budget ကို ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=budget_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "budget_menu")
def budget_menu(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "💰 <b>Budget</b> ကို ရွေးပါ။\n\n"
        "⌨️ မိမိသုံးမယ့်ငွေပမာဏကိုလည်း တိုက်ရိုက် ရိုက်ထည့်နိုင်ပါတယ်။",
        parse_mode="HTML",
        reply_markup=budget_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("budget_") and c.data != "budget_custom")
def budget_choice(call):
    bot.answer_callback_query(call.id)
    try:
        budget = int(call.data.replace("budget_", ""))
    except ValueError:
        return

    state = get_state(call.from_user.id)
    skin = state.get("skin", "")
    set_search_budget(call.from_user.id, budget)

    results = search_accounts(skin, budget)
    send_search_results(call.message.chat.id, results)


@bot.callback_query_handler(func=lambda c: c.data == "budget_custom")
def budget_custom(call):
    bot.answer_callback_query(call.id)
    set_state(call.from_user.id, {
        **get_state(call.from_user.id),
        "flow": "buy_budget_custom"
    })
    msg = bot.send_message(
        call.message.chat.id,
        "⌨️ <b>သုံးမယ့် Budget ပမာဏ</b> ကို ဂဏန်းနဲ့ ရိုက်ထည့်ပါ။\n\n"
        "ဥပမာ: 150000 သို့မဟုတ် 150,000",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    bot.register_next_step_handler(msg, receive_custom_budget)


def receive_custom_budget(message):
    user_id = message.from_user.id
    if not message.text:
        bot.send_message(user_id, "⚠️ Budget ကို ဂဏန်းနဲ့ ရိုက်ပေးပါ။")
        return

    try:
        budget = int(message.text.replace(",", "").replace(" ", "").strip())
        if budget <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(
            user_id,
            "❌ Budget မမှန်ပါ။ ဥပမာ <b>150000</b> လို့ ရိုက်ပါ။",
            parse_mode="HTML",
            reply_markup=back_button()
        )
        return

    state = get_state(user_id)
    skin = state.get("skin", "")
    set_search_budget(user_id, budget)

    results = search_accounts(skin, budget)
    send_search_results(user_id, results)


# =========================================================
# BROWSE ACCOUNTS
# =========================================================

def browse_index(user_id):
    state = get_state(user_id)
    return int(state.get("browse_index", 0))


@bot.callback_query_handler(func=lambda c: c.data.startswith("browse_") and c.data not in ("browse_next",))
def browse_accounts(call):
    bot.answer_callback_query(call.id)
    log_user_activity(call.from_user, "browse")

    try:
        idx = int(call.data.replace("browse_", ""))
    except ValueError:
        idx = 0

    accounts = get_available_accounts()
    if not accounts:
        bot.send_message(
            call.message.chat.id,
            "❌ လောလောဆယ် ပြသရန် အကောင့် မရှိသေးပါ။",
            reply_markup=back_button()
        )
        return

    idx %= len(accounts)
    set_state(call.from_user.id, {
        "flow": "browse",
        "browse_index": idx
    })

    acc = accounts[idx]

    # IMPORTANT: Account တင်ထားတဲ့ original Telegram photos ၅ ပုံသာ။
    send_account_photos(call.message.chat.id, acc, include_menu=True)


@bot.callback_query_handler(func=lambda c: c.data == "browse_next")
def browse_next(call):
    bot.answer_callback_query(call.id)
    accounts = get_available_accounts()

    if not accounts:
        bot.send_message(
            call.message.chat.id,
            "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။",
            reply_markup=back_button()
        )
        return

    idx = browse_index(call.from_user.id)
    idx = (idx + 1) % len(accounts)

    set_state(call.from_user.id, {
        "flow": "browse",
        "browse_index": idx
    })

    send_account_photos(call.message.chat.id, accounts[idx], include_menu=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("detail_"))
def account_detail(call):
    bot.answer_callback_query(call.id)
    account_id = call.data.replace("detail_", "", 1)
    acc = get_account_by_text_id(account_id)

    if not acc:
        bot.send_message(call.message.chat.id, "❌ ဒီအကောင့် မရှိတော့ပါ။")
        return

    photos = acc["photos"][:15]
    if photos:
        try:
            send_photo_batches(call.message.chat.id, photos, 10)
        except Exception:
            logging.exception("Detail photo send failed")

    bot.send_message(
        call.message.chat.id,
        "🔍 <b>အကောင့်အသေးစိတ်</b>\n\n" + format_account(acc),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 ဝယ်မယ် 💎", callback_data=f"buy_confirm_{acc['id']}")],
            [InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")]
        ])
    )


# =========================================================
# BUY CONFIRM
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_confirm_"))
def buy_confirm(call):
    bot.answer_callback_query(call.id)
    account_id = call.data.replace("buy_confirm_", "", 1)
    acc = get_account_by_text_id(account_id)

    if not acc or acc["status"] != "available":
        bot.send_message(
            call.message.chat.id,
            "❌ ဒီအကောင့် လက်ရှိ ဝယ်ယူလို့ မရတော့ပါ။",
            reply_markup=back_button()
        )
        return

    username = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "Admin"
    log_user_activity(call.from_user, "buy_click", f"{acc['id']} | {acc['effective_price']:,}")
    markup = InlineKeyboardMarkup(row_width=1)

    if ADMIN_USERNAME:
        markup.add(
            InlineKeyboardButton(
                "👨‍💻 Admin ထံ တိုက်ရိုက်ဆက်သွယ်မည် 🚀",
                url=f"https://t.me/{ADMIN_USERNAME}"
            )
        )
    markup.add(
        InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")
    )

    bot.send_message(
        call.message.chat.id,
        f"🛒 <b>{acc['id']}</b> ကို ဝယ်ယူလိုပါသလား?\n\n"
        f"{format_account(acc)}\n\n"
        f"👨‍💻 {username} ထံ တိုက်ရိုက်ဆက်သွယ်ပြီး ဝယ်ယူနိုင်ပါတယ်။",
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================================================
# SELL FLOW
# =========================================================


@bot.callback_query_handler(func=lambda c: c.data == "sell_start")
def sell_start(call):
    bot.answer_callback_query(call.id)
    clear_state(call.from_user.id)
    set_state(call.from_user.id, {
        "flow": "sell_photos",
        "photos": [],
        "photo_prompt_sent": False,
    })
    log_user_activity(call.from_user, "sell_start")
    bot.send_message(
        call.message.chat.id,
        "💰 <b>အကောင့်ရောင်းမယ်</b>\n\n"
        "📸 Account ပုံ <b>အများဆုံး 15 ပုံ</b> ကို <b>တစ်ခါတည်း Album</b> အနေနဲ့ ပို့ပါ။\n\n"
        "❌ Game / Skin / Error / ရောင်းလိုဈေးကို အခု မပို့ပါနဲ့။\n"
        "ပုံအားလုံးရောက်ပြီးမှ Bot က လိုအပ်တာတွေ တစ်ဆင့်ချင်း မေးပါမယ်။",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.message_handler(content_types=["photo"])
def receive_photo_message(message):
    user_id = message.from_user.id
    state = get_state(user_id)
    flow = state.get("flow")

    # Seller upload
    if flow == "sell_photos":
        photos = state.get("photos", [])
        if len(photos) >= 15:
            return
        photos.append(message.photo[-1].file_id)
        state["photos"] = photos

        # Do not spam one message per photo. Show one confirmation button only.
        if not state.get("photo_prompt_sent"):
            state["photo_prompt_sent"] = True
            set_state(user_id, state)
            bot.send_message(
                user_id,
                "📸 ပုံတွေ လက်ခံနေပါတယ်။\n"
                "ပုံအားလုံးပို့ပြီးမှ အောက်က Button ကိုနှိပ်ပါ။",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ ပုံအကုန်ပြီးပြီ", callback_data="sell_photos_done")],
                    [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
                ])
            )
        else:
            set_state(user_id, state)
        return

    # Admin upload. This MUST be here because an earlier generic photo handler
    # used to consume admin photos before receive_admin_photo could run.
    if user_id == ADMIN_ID and flow == "admin_photos":
        photos = state.get("photos", [])
        if len(photos) >= 15:
            return
        photos.append(message.photo[-1].file_id)
        state["photos"] = photos

        if not state.get("photo_prompt_sent"):
            state["photo_prompt_sent"] = True
            set_state(ADMIN_ID, state)
            bot.send_message(
                ADMIN_ID,
                "📸 ပုံတွေ လက်ခံနေပါတယ်။\n"
                "အနည်းဆုံး <b>10 ပုံ</b> ပြည့်ပြီးမှ အောက်က Button ကိုနှိပ်ပါ။",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ ပုံအကုန်တင်ပြီးပြီ", callback_data="admin_save")],
                    [InlineKeyboardButton("❌ မသိမ်းဘူး", callback_data="admin_cancel")]
                ])
            )
        else:
            set_state(ADMIN_ID, state)
        return


@bot.callback_query_handler(func=lambda c: c.data == "sell_photos_done")
def sell_photos_done(call):
    user_id = call.from_user.id
    state = get_state(user_id)
    photos = state.get("photos", [])

    if state.get("flow") != "sell_photos":
        bot.answer_callback_query(call.id, "Seller Flow မရှိတော့ပါ။", show_alert=True)
        return
    if not photos:
        bot.answer_callback_query(call.id, "အရင်ဆုံး Account ပုံတွေ ပို့ပါ။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    state["flow"] = "sell_error"
    set_state(user_id, state)
    bot.send_message(
        user_id,
        "⚠️ <b>Account မှာ Error ရှိပါသလား?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ ရှိပါတယ်", callback_data="sell_error_yes"),
                InlineKeyboardButton("❌ မရှိပါ", callback_data="sell_error_no")
            ],
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.callback_query_handler(func=lambda c: c.data in ("sell_error_yes", "sell_error_no"))
def seller_error_choice(call):
    user_id = call.from_user.id
    state = get_state(user_id)
    if state.get("flow") != "sell_error":
        bot.answer_callback_query(call.id, "Flow မရှိတော့ပါ။", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    if call.data == "sell_error_yes":
        state["flow"] = "sell_error_text"
        set_state(user_id, state)
        bot.send_message(
            user_id,
            "⚠️ Error အကြောင်းကို တိုတိုရှင်းရှင်း ရေးပေးပါ။",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
            ])
        )
        return

    state["error_info"] = "မရှိပါ"
    state["flow"] = "sell_binding"
    set_state(user_id, state)
    bot.send_message(
        user_id,
        "🔗 <b>Account ဘာနဲ့ချိတ်ထားလဲ?</b>\n\n"
        "ဥပမာ — Moonton / Facebook / Google / TikTok / Apple / အခြား",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.message_handler(
    func=lambda m: get_state(m.from_user.id).get("flow") == "sell_error_text",
    content_types=["text"]
)
def seller_error_text(message):
    text = (message.text or "").strip()
    if not text:
        bot.send_message(message.from_user.id, "⚠️ Error အကြောင်းကို စာနဲ့ ရေးပေးပါ။")
        return
    state = get_state(message.from_user.id)
    state["error_info"] = text
    state["flow"] = "sell_binding"
    set_state(message.from_user.id, state)
    bot.send_message(
        message.from_user.id,
        "🔗 <b>Account ဘာနဲ့ချိတ်ထားလဲ?</b>\n\n"
        "ဥပမာ — Moonton / Facebook / Google / TikTok / Apple / အခြား",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.message_handler(
    func=lambda m: get_state(m.from_user.id).get("flow") == "sell_binding",
    content_types=["text"]
)
def seller_binding_text(message):
    text = (message.text or "").strip()
    if not text:
        bot.send_message(message.from_user.id, "🔗 ချိတ်ထားတဲ့ Account အမျိုးအစားကို ရေးပေးပါ။")
        return

    state = get_state(message.from_user.id)
    state["binding_info"] = text
    state["flow"] = "sell_moonton"
    set_state(message.from_user.id, state)
    bot.send_message(
        message.from_user.id,
        "📧 <b>Moonton Mail ချိန်းလို့ရပါသလား?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ ချိန်းလို့ရ", callback_data="sell_moonton_yes"),
                InlineKeyboardButton("❌ ချိန်းလို့မရ", callback_data="sell_moonton_no")
            ],
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.callback_query_handler(func=lambda c: c.data in ("sell_moonton_yes", "sell_moonton_no"))
def seller_moonton_choice(call):
    user_id = call.from_user.id
    state = get_state(user_id)
    if state.get("flow") != "sell_moonton":
        bot.answer_callback_query(call.id, "Flow မရှိတော့ပါ။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    state["moonton_change"] = "ချိန်းလို့ရ" if call.data == "sell_moonton_yes" else "ချိန်းလို့မရ"
    state["flow"] = "sell_estimated_price"
    set_state(user_id, state)

    bot.send_message(
        user_id,
        "💰 <b>သင်ခန့်မှန်းလိုတဲ့ ရောင်းဈေး</b> ကို ရိုက်ပေးပါ။\n"
        "ဥပမာ <code>100000</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ရပ်မယ်", callback_data="sell_cancel")]
        ])
    )


@bot.message_handler(
    func=lambda m: get_state(m.from_user.id).get("flow") == "sell_estimated_price",
    content_types=["text"]
)
def seller_estimated_price(message):
    user_id = message.from_user.id
    try:
        estimated = int((message.text or "").replace(",", "").replace(" ", "").strip())
        if estimated <= 0:
            raise ValueError
    except Exception:
        bot.send_message(
            user_id,
            "❌ ခန့်မှန်းဈေး မမှန်ပါ။ ဥပမာ <code>100000</code>",
            parse_mode="HTML"
        )
        return

    state = get_state(user_id)
    photos = state.get("photos", [])[:15]
    username = message.from_user.username or "No Username"

    with db_lock:
        with closing(db_connect()) as conn:
            cur = conn.execute("""
                INSERT INTO seller_requests(
                    user_id, username, error_info, price, photo_count, status, photos,
                    binding_info, moonton_change, estimated_price,
                    admin_payout_price, listing_price
                )
                VALUES(?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, NULL, NULL)
            """, (
                user_id, username,
                state.get("error_info", "မရှိပါ"),
                estimated,
                len(photos),
                ",".join(photos),
                state.get("binding_info", ""),
                state.get("moonton_change", ""),
                estimated
            ))
            request_id = cur.lastrowid
            conn.commit()

    clear_state(user_id)
    log_user_activity(
        message.from_user,
        "seller_submit",
        f"request={request_id}, photos={len(photos)}, estimated={estimated:,}"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ အတည်ပြုမယ်", callback_data=f"seller_approve_{request_id}"),
            InlineKeyboardButton("❌ ငြင်းမယ်", callback_data=f"seller_reject_req_{request_id}")
        ]
    ])

    admin_text = (
        f"📥 <b>Seller Request #{request_id}</b>\n\n"
        f"👤 @{username}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📸 <b>{len(photos)}</b> ပုံ\n"
        f"⚠️ Error — <b>{state.get('error_info', 'မရှိပါ')}</b>\n"
        f"🔗 ချိတ်ထားတာ — <b>{state.get('binding_info', '')}</b>\n"
        f"📧 Moonton Mail ချိန်း — <b>{state.get('moonton_change', '')}</b>\n"
        f"💰 Seller ခန့်မှန်းဈေး — <b>{estimated:,} MMK</b>\n\n"
        "ပုံတွေနဲ့ အချက်အလက်အားလုံးကို စစ်ပြီး အတည်ပြု/ငြင်းပါ။"
    )
    bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=markup)
    send_photo_batches(ADMIN_ID, photos, 10)

    bot.send_message(
        user_id,
        "✅ <b>အချက်အလက်အားလုံးကို Admin ဆီ ပို့ပြီးပါပြီ။</b>\n\n"
        "Admin စစ်ဆေးပြီး အတည်ပြုချက်ကို စောင့်ပေးပါ။",
        parse_mode="HTML",
        reply_markup=back_button()
    )


@bot.callback_query_handler(func=lambda c: c.data == "sell_cancel")
def sell_cancel(call):
    clear_state(call.from_user.id)
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "❌ ရောင်းရန်တင်ခြင်း ပယ်ဖျက်ပြီးပါပြီ။",
        reply_markup=main_menu(call.from_user.id)
    )



@bot.callback_query_handler(func=lambda c: c.data == "seller_requests")
def seller_requests_menu(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    with db_lock:
        with closing(db_connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM seller_requests WHERE status='pending' ORDER BY id DESC LIMIT 20"
            ).fetchall()

    if not rows:
        bot.send_message(ADMIN_ID, "📥 Pending Seller Request မရှိပါ။", reply_markup=admin_keyboard())
        return

    bot.send_message(
        ADMIN_ID,
        f"📥 <b>Pending Seller Requests — {len(rows)}</b>",
        parse_mode="HTML"
    )

    for row in rows:
        photos = [x for x in row["photos"].split(",") if x][:15]
        estimated = row["estimated_price"] if "estimated_price" in row.keys() and row["estimated_price"] else row["price"]
        binding = row["binding_info"] if "binding_info" in row.keys() else ""
        moonton = row["moonton_change"] if "moonton_change" in row.keys() else ""

        text = (
            f"📥 <b>Request #{row['id']}</b>\n"
            f"👤 @{row['username'] or 'No Username'}\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"📸 {len(photos)} ပုံ\n"
            f"⚠️ Error — <b>{row['error_info'] or 'မရှိပါ'}</b>\n"
            f"🔗 ချိတ်ထားတာ — <b>{binding}</b>\n"
            f"📧 Moonton Mail ချိန်း — <b>{moonton}</b>\n"
            f"💰 Seller ခန့်မှန်းဈေး — <b>{estimated:,} MMK</b>\n\n"
            "ပုံတွေနဲ့ အချက်အလက်အားလုံးကို စစ်ပါ။"
        )
        bot.send_message(
            ADMIN_ID,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ အတည်ပြုမယ်", callback_data=f"seller_approve_{row['id']}"),
                    InlineKeyboardButton("❌ ငြင်းမယ်", callback_data=f"seller_reject_req_{row['id']}")
                ]
            ])
        )
        send_photo_batches(ADMIN_ID, photos, 10)


@bot.callback_query_handler(func=lambda c: c.data.startswith("seller_approve_"))
def seller_approve(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    request_id = int(call.data.replace("seller_approve_", "", 1))
    with db_lock:
        with closing(db_connect()) as conn:
            row = conn.execute(
                "SELECT * FROM seller_requests WHERE id=?",
                (request_id,)
            ).fetchone()

    if not row or row["status"] != "pending":
        bot.answer_callback_query(call.id, "Request မရှိတော့ပါ။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    set_state(ADMIN_ID, {
        "flow": "seller_set_payout",
        "request_id": request_id,
    })

    msg = bot.send_message(
        ADMIN_ID,
        f"✅ Request #{request_id} ကို အတည်ပြုလိုက်ပါပြီ။\n\n"
        "🔐 <b>Seller ကိုပေးမယ့်ဈေး</b> ကို အရင်ရိုက်ပါ။\n"
        "ဒီဈေးက <b>PRIVATE</b> ဖြစ်ပြီး Seller ကို မပြပါ။\n\n"
        "ဥပမာ — <code>70000</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ပယ်ဖျက်မယ်", callback_data="seller_price_cancel")]
        ])
    )
    bot.register_next_step_handler(msg, seller_set_payout)


@bot.callback_query_handler(func=lambda c: c.data == "seller_price_cancel")
def seller_price_cancel(call):
    if call.from_user.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    clear_state(ADMIN_ID)
    bot.send_message(ADMIN_ID, "❌ Seller price သတ်မှတ်ခြင်း ပယ်ဖျက်ပြီးပါပြီ။", reply_markup=admin_keyboard())


def seller_set_payout(message):
    if message.from_user.id != ADMIN_ID:
        return

    state = get_state(ADMIN_ID)
    if state.get("flow") != "seller_set_payout":
        return

    try:
        payout = int((message.text or "").replace(",", "").replace(" ", "").strip())
        if payout <= 0:
            raise ValueError
    except Exception:
        msg = bot.send_message(
            ADMIN_ID,
            "❌ Seller ကိုပေးမယ့်ဈေး မမှန်ပါ။ ဥပမာ <code>70000</code>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, seller_set_payout)
        return

    state["seller_payout_price"] = payout
    state["flow"] = "seller_set_listing"
    set_state(ADMIN_ID, state)

    msg = bot.send_message(
        ADMIN_ID,
        "🏷️ <b>Marketplace မှာ ပြန်တင်ရောင်းမယ့်ဈေး</b> ကို ရိုက်ပါ။\n"
        "ဒီဈေးက <b>PRIVATE</b> ဖြစ်ပြီး Seller ကို မပြပါ။\n\n"
        "ဥပမာ — <code>95000</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ပယ်ဖျက်မယ်", callback_data="seller_price_cancel")]
        ])
    )
    bot.register_next_step_handler(msg, seller_set_listing)


def seller_set_listing(message):
    if message.from_user.id != ADMIN_ID:
        return

    state = get_state(ADMIN_ID)
    if state.get("flow") != "seller_set_listing":
        return

    try:
        listing = int((message.text or "").replace(",", "").replace(" ", "").strip())
        if listing <= 0:
            raise ValueError
    except Exception:
        msg = bot.send_message(
            ADMIN_ID,
            "❌ Marketplace ဈေး မမှန်ပါ။ ဥပမာ <code>95000</code>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, seller_set_listing)
        return

    request_id = state["request_id"]
    payout = int(state["seller_payout_price"])

    if listing < payout:
        msg = bot.send_message(
            ADMIN_ID,
            f"❌ Marketplace ဈေး <b>{listing:,} MMK</b> က Seller ပေးဈေး "
            f"<b>{payout:,} MMK</b> ထက် နည်းနေပါတယ်။\n"
            "Marketplace ဈေးကို Seller ပေးဈေးထက် တူသို့မဟုတ် ပိုများအောင် ထည့်ပါ။",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, seller_set_listing)
        return

    with db_lock:
        with closing(db_connect()) as conn:
            row = conn.execute(
                "SELECT * FROM seller_requests WHERE id=?",
                (request_id,)
            ).fetchone()

            if not row or row["status"] != "pending":
                clear_state(ADMIN_ID)
                bot.send_message(ADMIN_ID, "❌ Request မရှိတော့ပါ။", reply_markup=admin_keyboard())
                return

            photos = [x for x in row["photos"].split(",") if x][:15]
            if not photos:
                clear_state(ADMIN_ID)
                bot.send_message(ADMIN_ID, "❌ Request ထဲမှာ ပုံမရှိပါ။", reply_markup=admin_keyboard())
                return

            number = next_account_number()

            conn.execute("""
                INSERT INTO accounts(
                    id, title, skins, price, photos, status,
                    original_price, sale_price, is_featured,
                    seller_user_id, seller_username, seller_payout_price
                )
                VALUES(?,?,?,?,?,'available',?,NULL,0,?,?,?)
            """, (
                number,
                "ML Account",
                "",
                listing,
                ",".join(photos),
                listing,
                row["user_id"],
                row["username"],
                payout
            ))

            conn.execute("""
                UPDATE seller_requests
                SET status='accepted',
                    admin_payout_price=?,
                    listing_price=?,
                    price=?
                WHERE id=?
            """, (payout, listing, listing, request_id))
            conn.commit()

    account_id = make_account_id(number)
    clear_state(ADMIN_ID)

    log_user_activity(
        message.from_user,
        "seller_publish",
        f"request={request_id}, account={account_id}, payout={payout:,}, listing={listing:,}"
    )

    # Admin sees both prices. Seller never sees either price.
    bot.send_message(
        ADMIN_ID,
        f"🎉 <b>{account_id}</b> Marketplace ထဲ တင်ပြီးပါပြီ။\n\n"
        f"🔐 Seller ပေးဈေး — <b>{payout:,} MMK</b> (PRIVATE)\n"
        f"🏷️ ပြန်တင်ရောင်းဈေး — <b>{listing:,} MMK</b> (PRIVATE)",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )

    try:
        seller_name = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "Admin"
        if ADMIN_USERNAME:
            seller_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👑 Admin ထံ တိုက်ရိုက်ဆက်သွယ်မည်",
                    url=f"https://t.me/{ADMIN_USERNAME}"
                )]
            ])
        else:
            seller_markup = back_button()

        bot.send_message(
            row["user_id"],
            "✅ <b>သင့်အကောင့်ကို Admin က အတည်ပြုလိုက်ပါပြီ။</b>\n\n"
            f"👑 Admin — <b>{seller_name}</b>",
            parse_mode="HTML",
            reply_markup=seller_markup
        )
    except Exception:
        logging.exception("Seller approval notification failed")


@bot.callback_query_handler(func=lambda c: c.data.startswith("seller_reject_req_"))
def seller_reject_req(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    request_id = int(call.data.replace("seller_reject_req_", "", 1))
    with db_lock:
        with closing(db_connect()) as conn:
            row = conn.execute(
                "SELECT user_id FROM seller_requests WHERE id=?",
                (request_id,)
            ).fetchone()
            conn.execute(
                "UPDATE seller_requests SET status='rejected' WHERE id=?",
                (request_id,)
            )
            conn.commit()

    bot.answer_callback_query(call.id, "Rejected")
    if row:
        try:
            bot.send_message(row["user_id"], "❌ Admin က ဒီ Account ကို အတည်ပြုမထားပါဘူး။")
        except Exception:
            pass

    bot.send_message(
        ADMIN_ID,
        "❌ Seller Request ကို ငြင်းပယ်ပြီးပါပြီ။",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_analysis")
def admin_analysis(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(
        ADMIN_ID,
        admin_analysis_text(),
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "seller_analysis")
def seller_analysis(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(
        ADMIN_ID,
        seller_analysis_text(),
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "recent_activity")
def recent_activity(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(
        ADMIN_ID,
        recent_activity_text(),
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "admin_add")
def admin_add(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    set_state(ADMIN_ID, {"flow": "admin_info"})

    msg = bot.send_message(
        ADMIN_ID,
        "➕ <b>အကောင့်အသစ်တင်မယ်</b>\n\n"
        "အရင်ဆုံး <b>ခေါင်းစဉ်</b> ရိုက်ပါ။\n"
        "ပြီးရင် Account ပုံ <b>အနည်းဆုံး 10 ပုံ / အများဆုံး 15 ပုံ</b> ကို "
        "<b>တစ်ခါတည်း Album</b> အနေနဲ့ ပို့ပါ။",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, process_admin_info)


@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and get_state(ADMIN_ID).get("flow") == "admin_info",
    content_types=["text"]
)
def process_admin_info(message):
    title = (message.text or "").strip() or "ML Account"

    set_state(ADMIN_ID, {
        "flow": "admin_photos",
        "title": title,
        "photos": [],
        "photo_prompt_sent": False,
    })

    bot.send_message(
        ADMIN_ID,
        "📸 <b>ပုံအားလုံးကို တစ်ခါတည်း ပို့ပါ</b>\n\n"
        "အနည်းဆုံး <b>10 ပုံ</b>၊ အများဆုံး <b>15 ပုံ</b> ပါ။\n"
        "အားလုံးပို့ပြီးမှ <b>ပုံအကုန်တင်ပြီးပြီ</b> ကိုနှိပ်ပါ။",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ မသိမ်းဘူး", callback_data="admin_cancel")]
        ])
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_save")
def admin_save(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    state = get_state(ADMIN_ID)
    photos = state.get("photos", [])

    if state.get("flow") != "admin_photos":
        bot.answer_callback_query(call.id, "အကောင့်တင်တဲ့ Flow မရှိတော့ပါ။", show_alert=True)
        return

    if len(photos) < 10:
        bot.answer_callback_query(
            call.id,
            f"အနည်းဆုံး 10 ပုံ လိုပါတယ်။ လက်ရှိ {len(photos)} ပုံပဲ ရှိပါတယ်။",
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id)
    set_state(ADMIN_ID, {
        **state,
        "flow": "admin_set_price",
        "photos": photos[:15],
    })

    msg = bot.send_message(
        ADMIN_ID,
        "💰 ဒီ Account အတွက် <b>Marketplace ရောင်းဈေး</b> ကို ရိုက်ပါ။\n"
        "ဥပမာ <code>95000</code>",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, admin_set_price)


def admin_set_price(message):
    if message.from_user.id != ADMIN_ID:
        return

    state = get_state(ADMIN_ID)
    if state.get("flow") != "admin_set_price":
        return

    try:
        price = int((message.text or "").replace(",", "").replace(" ", "").strip())
        if price <= 0:
            raise ValueError
    except Exception:
        msg = bot.send_message(
            ADMIN_ID,
            "❌ Price မမှန်ပါ။ ဥပမာ <code>95000</code>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, admin_set_price)
        return

    photos = state.get("photos", [])[:15]
    if len(photos) < 10:
        clear_state(ADMIN_ID)
        bot.send_message(
            ADMIN_ID,
            "❌ Account မသိမ်းနိုင်ပါ။ အနည်းဆုံး 10 ပုံ လိုပါတယ်။",
            reply_markup=admin_keyboard()
        )
        return

    account_id = save_account(
        state.get("title") or "ML Account",
        "",
        price,
        photos,
        original_price=price,
        sale_price=None,
        is_featured=0
    )

    clear_state(ADMIN_ID)
    bot.send_message(
        ADMIN_ID,
        f"🎉 <b>{account_id}</b> တင်ပြီးပါပြီ။\n"
        f"💰 {price:,} MMK\n"
        f"📸 {len(photos)} ပုံ",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_cancel")
def admin_cancel(call):
    if call.from_user.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    clear_state(ADMIN_ID)
    bot.send_message(ADMIN_ID, "❌ မသိမ်းတော့ပါ။", reply_markup=admin_keyboard())


# =========================================================
# DISCOUNT
# =========================================================
# discount_remove_ MUST be registered before generic discount_.
# The old order caused the remove callback to be parsed as a normal
# discount callback and produced the "Account မတွေ့ပါ" behavior.

@bot.callback_query_handler(func=lambda c: c.data.startswith("discount_remove_"))
def admin_discount_remove(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    account_id = call.data.replace("discount_remove_", "", 1)
    acc = get_account_by_text_id(account_id)

    if not acc:
        bot.answer_callback_query(call.id, "Account မတွေ့ပါ။", show_alert=True)
        return

    with db_lock:
        with closing(db_connect()) as conn:
            conn.execute("UPDATE accounts SET sale_price=NULL WHERE id=?", (acc["db_id"],))
            conn.commit()

    clear_state(ADMIN_ID)
    bot.answer_callback_query(call.id, "လျော့စျေးဖြုတ်ပြီးပါပြီ")

    updated = get_account_by_text_id(account_id)
    bot.send_message(
        ADMIN_ID,
        f"✅ <b>{account_id}</b> လျော့စျေးဖြုတ်ပြီးပါပြီ။\n\n{format_account(updated)}",
        parse_mode="HTML",
        reply_markup=account_action_keyboard(updated, admin=True, include_menu=False)
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_discount_list")
def admin_discount_list(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    accounts = get_admin_accounts(status="available")

    if not accounts:
        bot.send_message(
            ADMIN_ID,
            "📦 လက်ရှိ Available Account မရှိသေးပါ။",
            reply_markup=admin_keyboard()
        )
        return

    bot.send_message(
        ADMIN_ID,
        "💸 <b>လျော့စျေးတင်/ပြင်/ဖြုတ်ရန် Account ရွေးပါ</b>",
        parse_mode="HTML"
    )

    for acc in accounts[:30]:
        buttons = [[
            InlineKeyboardButton(
                "💸 လျော့စျေးသတ်မှတ် / ပြင်မယ်",
                callback_data=f"discount_{acc['id']}"
            )
        ]]
        if acc["is_discounted"]:
            buttons.append([
                InlineKeyboardButton(
                    "❌ လျော့စျေးဖြုတ်မယ်",
                    callback_data=f"discount_remove_{acc['id']}"
                )
            ])

        bot.send_message(
            ADMIN_ID,
            format_account(acc),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("discount_")
    and c.data not in ("discount_menu",)
    and not c.data.startswith("discount_remove_")
)
def admin_discount_start(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    account_id = call.data.replace("discount_", "", 1)
    acc = get_account_by_text_id(account_id)

    if not acc:
        bot.answer_callback_query(call.id, "Account မတွေ့ပါ။", show_alert=True)
        return

    if acc["status"] != "available":
        bot.answer_callback_query(
            call.id,
            "Available Account မှာပဲ လျော့စျေးတင်နိုင်ပါတယ်။",
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id)
    set_state(ADMIN_ID, {
        "flow": "discount_price",
        "account_id": account_id,
    })

    msg = bot.send_message(
        ADMIN_ID,
        f"💸 <b>{account_id}</b>\n"
        f"မူရင်းဈေး — {acc['price']:,} MMK\n\n"
        "လျော့ပြီးဈေးကို ရိုက်ပါ။",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "❌ လျော့စျေးဖြုတ်မယ်",
                callback_data=f"discount_remove_{account_id}"
            )],
            [InlineKeyboardButton("🔙 Discount Menu", callback_data="admin_discount_list")]
        ])
    )
    bot.register_next_step_handler(msg, admin_discount_price)


@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and get_state(ADMIN_ID).get("flow") == "discount_price",
    content_types=["text"]
)
def admin_discount_price(message):
    state = get_state(ADMIN_ID)

    try:
        sale = int((message.text or "").replace(",", "").replace(" ", "").strip())
        if sale <= 0:
            raise ValueError
    except Exception:
        msg = bot.send_message(
            ADMIN_ID,
            "❌ ဈေးမမှန်ပါ။ ဥပမာ <code>80000</code>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, admin_discount_price)
        return

    acc = get_account_by_text_id(state.get("account_id", ""))
    if not acc:
        clear_state(ADMIN_ID)
        bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_keyboard())
        return

    if sale >= acc["price"]:
        msg = bot.send_message(
            ADMIN_ID,
            f"❌ လျော့စျေးက မူရင်း {acc['price']:,} MMK ထက် နည်းရပါမယ်။",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, admin_discount_price)
        return

    with db_lock:
        with closing(db_connect()) as conn:
            conn.execute(
                "UPDATE accounts SET original_price=price,sale_price=? WHERE id=?",
                (sale, acc["db_id"])
            )
            conn.commit()

    clear_state(ADMIN_ID)
    updated = get_account_by_text_id(acc["id"])
    log_user_activity(message.from_user, "discount_set", f"{acc['id']} -> {sale:,}")

    bot.send_message(
        ADMIN_ID,
        f"💸 <b>{acc['id']}</b> လျော့စျေးတင်ပြီးပါပြီ။\n\n{format_account(updated)}",
        parse_mode="HTML",
        reply_markup=account_action_keyboard(updated, admin=True, include_menu=False)
    )


@bot.callback_query_handler(func=lambda c: c.data == "discount_menu")
def discount_menu(call):
    bot.answer_callback_query(call.id)
    accounts = get_discounted_accounts()
    log_user_activity(call.from_user, "discount_browse", f"count={len(accounts)}")

    if not accounts:
        bot.send_message(
            call.message.chat.id,
            "💸 လျော့စျေးတင်ထားတဲ့ Account မရှိသေးပါ။",
            reply_markup=back_button()
        )
        return

    bot.send_message(
        call.message.chat.id,
        f"💸 <b>လျော့စျေးအကောင့်များ</b> — {len(accounts)} ခု",
        parse_mode="HTML"
    )
    for acc in accounts[:15]:
        send_account_photos(call.message.chat.id, acc, include_menu=False)


# =========================================================
# TIPS ၅ ခု
# =========================================================

TIPS = {
    1: (
        "🔐 <b>Account လုံခြုံရေး</b>\n\n"
        "Account ဝယ်ပြီးရင် Login အချက်အလက်တွေကို မျှဝေမထားပါနဲ့။ "
        "ကိုယ်ပိုင် Security Setting တွေကို ပြန်စစ်ပါ။"
    ),
    2: (
        "📧 <b>Email / Password</b>\n\n"
        "Account လက်ခံရရှိပြီးနောက် Email နဲ့ Password ကို ကိုယ်ပိုင်အချက်အလက်အသစ်နဲ့ ပြောင်းထားတာ ပိုလုံခြုံပါတယ်။"
    ),
    3: (
        "🛡️ <b>2-Step Verification</b>\n\n"
        "ရနိုင်တဲ့ Account တွေမှာ 2-Step Verification ကို ဖွင့်ထားပါ။ "
        "Login ပြောင်းလဲမှုတွေကိုလည်း သတိထားစစ်ဆေးပါ။"
    ),
    4: (
        "💳 <b>ငွေပေးချေမှု သတိပြုရန်</b>\n\n"
        "ငွေလွှဲမယ့်အခါ Admin ရဲ့ မှန်ကန်တဲ့ Account ကို သေချာစစ်ပြီးမှ ငွေလွှဲပါ။ "
        "အတည်ပြုမထားတဲ့ Payment Screenshot တစ်ခုတည်းကို မယုံပါနဲ့။"
    ),
    5: (
        "⚠️ <b>Scam မဖြစ်အောင် သတိထားရန်</b>\n\n"
        "Admin အဖြစ် အယောင်ဆောင်တဲ့ Account တွေကို သတိထားပါ။ "
        "Bot ထဲက သတ်မှတ်ထားတဲ့ Admin Contact ကိုသာ အသုံးပြုပါ။"
    ),
}


@bot.callback_query_handler(func=lambda c: c.data == "tips_menu")
def tips_menu(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "💡 <b>အသုံးဝင်တဲ့ Tips ၅ ခု</b>\n\n"
        "လိုချင်တဲ့ Tip ကို ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=tips_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("tip_"))
def tip_detail(call):
    bot.answer_callback_query(call.id)

    try:
        number = int(call.data.replace("tip_", ""))
    except ValueError:
        return

    text = TIPS.get(number)
    if not text:
        return

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💡 Tips Menu", callback_data="tips_menu"),
        InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")
    )

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================================================
# FALLBACK TEXT
# =========================================================

@bot.message_handler(func=lambda m: True, content_types=["text"])
def fallback_text(message):
    user_id = message.from_user.id
    state = get_state(user_id)
    flow = state.get("flow")

    if flow == "buy_query":
        raw = message.text.strip()
        parts = [x.strip() for x in raw.split("|", 1)]

        if len(parts) != 2:
            # Also accept: "Gusion 200000"
            m = re.match(r"^(.*?)\s+([0-9][0-9, ]*)\s*$", raw)
            if m:
                parts = [m.group(1).strip(), m.group(2).strip()]

        if len(parts) != 2:
            bot.send_message(
                user_id,
                "❌ Format မမှန်ပါ။\n\n"
                "ဒီလို ရိုက်ပို့ပါ:\n"
                "<code>Gusion | 200000</code>\n"
                "သို့မဟုတ် <code>Collector 150000</code>",
                parse_mode="HTML"
            )
            return

        skin = parts[0].strip()
        if skin.lower() in ("any", "all", "အကုန်", "အားလုံး"):
            skin = ""
        budget_text = parts[1].replace(",", "").replace(" ", "")
        try:
            budget = int(budget_text)
            if budget <= 0:
                raise ValueError
        except ValueError:
            bot.send_message(user_id, "❌ Budget ကို ဂဏန်းနဲ့ ထည့်ပါ။ ဥပမာ 200000")
            return

        clear_state(user_id)
        log_user_activity(
            message.from_user,
            "buy_search",
            f"{skin} | {budget:,}"
        )
        results = search_accounts(skin, budget)
        send_search_results(user_id, results)
        return

    # next_step_handler normally handles active text input first.
    if flow in (
        "sell_photos", "sell_error", "sell_error_text", "sell_binding",
        "sell_moonton", "sell_estimated_price",
        "admin_info", "admin_photos", "admin_set_price",
        "seller_set_payout", "seller_set_listing", "discount_price",
    ):
        return
    if flow in ("buy_skin_custom", "buy_budget_custom"):
        return

    bot.send_message(
        user_id,
        "👇 အောက်က Menu ကို အသုံးပြုပါ။",
        reply_markup=main_menu(user_id)
    )


# =========================================================
# STARTUP
# =========================================================

init_db()

if PUBLIC_URL:
    try:
        bot.remove_webhook()
        bot.set_webhook(
            url=f"{PUBLIC_URL}/webhook/{TELEGRAM_TOKEN}",
            drop_pending_updates=True
        )
        logging.info("Webhook set: %s/webhook/...", PUBLIC_URL)
    except Exception:
        logging.exception("Webhook setup failed")
else:
    logging.warning(
        "PUBLIC_URL မရှိပါ။ Render မှာ Environment Variable ထည့်ပြီး redeploy လုပ်ပါ။"
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
