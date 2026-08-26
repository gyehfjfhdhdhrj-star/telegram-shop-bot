import os
import sqlite3
import threading
import logging
from contextlib import closing

import telebot
from flask import Flask, request
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

# =========================================================
# CONFIG
# =========================================================
# Render Environment Variables မှာ သတ်မှတ်ပါ:
# TELEGRAM_TOKEN = 8892803898:AAFWqTsr8GiHZ2Vr_ud9LttPp6I3qfmo-ew
# ADMIN_ID       = 7267372257
# ADMIN_USERNAME = AUNGGYIW
# PUBLIC_URL     = https://dashboard.render.com/web/srv-da66s26417fc739h0m1g/deploys/dep-da79n2gae00c73b5h8u0?r=2026-08-26%4007%3A52%3A46%7E2026-08-26%4007%3A55%3A28
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
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


def save_account(title, skins, price, photos):
    number = next_account_number()
    account_id = make_account_id(number)

    with db_lock:
        with closing(db_connect()) as conn:
            conn.execute("""
                INSERT INTO accounts(id, title, skins, price, photos, status)
                VALUES(?, ?, ?, ?, ?, 'available')
            """, (
                number,
                title,
                skins,
                price,
                ",".join(photos)
            ))
            conn.commit()

    return account_id


def row_to_account(row):
    return {
        "db_id": row["id"],
        "id": make_account_id(row["id"]),
        "title": row["title"],
        "skins": row["skins"],
        "price": row["price"],
        "photos": [x for x in row["photos"].split(",") if x],
        "status": row["status"],
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
                ORDER BY id ASC
            """).fetchall()
    return [row_to_account(row) for row in rows]


def search_accounts(skin_keyword="", max_price=None):
    keyword = (skin_keyword or "").strip().lower()

    with db_lock:
        with closing(db_connect()) as conn:
            if max_price is None:
                rows = conn.execute("""
                    SELECT * FROM accounts
                    WHERE status = 'available'
                    ORDER BY id ASC
                """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM accounts
                    WHERE status = 'available' AND price <= ?
                    ORDER BY price ASC, id ASC
                """, (max_price,)).fetchall()

    result = []
    for row in rows:
        acc = row_to_account(row)
        if not keyword or (
            keyword in acc["title"].lower()
            or keyword in acc["skins"].lower()
        ):
            result.append(acc)
    return result


# =========================================================
# UI HELPERS
# =========================================================

def main_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data="buy_menu"),
        InlineKeyboardButton("👀 အကောင့်တွေကြည့်မယ် 🚀", callback_data="browse_0"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည် 🔥", callback_data="sell_start"),
        InlineKeyboardButton("💡 အသုံးဝင်တဲ့ Tips ၅ ခု 📌", callback_data="tips_menu"),
    )

    if user_id == ADMIN_ID:
        markup.add(
            InlineKeyboardButton("👑 [ADMIN] အကောင့်အသစ်တင်ရန် ➕", callback_data="admin_add"),
            InlineKeyboardButton("📊 [ADMIN] လက်ကျန်အကောင့်များ 📂", callback_data="admin_list"),
        )
    return markup


def back_button():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်မည် 🏠", callback_data="home")
    )
    return markup


def buy_menu_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🌈 အကုန်လုံးကြည့်မယ်", callback_data="buy_all_skin"),
        InlineKeyboardButton("✨ Collector", callback_data="skin_Collector"),
        InlineKeyboardButton("🔥 Epic", callback_data="skin_Epic"),
        InlineKeyboardButton("💎 Legend", callback_data="skin_Legend"),
        InlineKeyboardButton("⌨️ ကိုယ်လိုချင်တဲ့ Skin နာမည် ရိုက်မယ်", callback_data="skin_custom"),
        InlineKeyboardButton("💰 Budget ရွေးမယ်", callback_data="budget_menu"),
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်မည် 🏠", callback_data="home"),
    )
    return markup


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
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("➕ အကောင့်အသစ်တင်ရန်", callback_data="admin_add"),
        InlineKeyboardButton("📂 လက်ကျန်အကောင့်များကြည့်ရန်", callback_data="admin_list"),
        InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home"),
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
    return (
        f"🆔 <b>{acc['id']}</b>\n"
        f"📝 {acc['title']}\n"
        f"✨ Skins: {acc['skins']}\n"
        f"💵 ဈေးနှုန်း: <b>{acc['price']:,} MMK</b>"
    )


def send_account_photos(chat_id, acc, include_menu=True):
    photos = acc["photos"][:5]

    if photos:
        media = [InputMediaPhoto(photo_id) for photo_id in photos]
        try:
            bot.send_media_group(chat_id, media)
        except Exception:
            # Telegram photo IDs can expire/become invalid.
            logging.exception("Could not send account photo group for %s", acc["id"])

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔍 ပုံအသေးစိတ် ပြန်ကြည့်မယ် 📸",
                             callback_data=f"detail_{acc['id']}"),
        InlineKeyboardButton("🛒 ဒီအကောင့် ဝယ်မယ် 💎",
                             callback_data=f"buy_confirm_{acc['id']}")
    )
    if include_menu:
        markup.add(
            InlineKeyboardButton("➡️ နောက်အကောင့်", callback_data="browse_next"),
            InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home"),
        )

    bot.send_message(
        chat_id,
        format_account(acc),
        parse_mode="HTML",
        reply_markup=markup
    )


def send_search_results(chat_id, results):
    if not results:
        bot.send_message(
            chat_id,
            "❌ သင့် Skin နာမည်နဲ့ Budget နဲ့ ကိုက်ညီတဲ့ အကောင့် မတွေ့ပါသေးပါ။",
            reply_markup=back_button()
        )
        return

    bot.send_message(
        chat_id,
        f"🎯 ကိုက်ညီတဲ့ အကောင့် <b>{len(results)}</b> ခု တွေ့ပါပြီ။",
        parse_mode="HTML"
    )

    for acc in results[:20]:
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
    set_state(call.from_user.id, {"flow": "buy"})
    bot.send_message(
        call.message.chat.id,
        "🛒 <b>အကောင့်ဝယ်မည်</b>\n\n"
        "✨ Skin ကို အောက်က Menu ကနေ ရွေးပါ။\n"
        "⌨️ ကိုယ်လိုချင်တဲ့ Skin နာမည်ကိုလည်း Menu ထဲကနေ တိုက်ရိုက် ရိုက်ထည့်နိုင်ပါတယ်။",
        parse_mode="HTML",
        reply_markup=buy_menu_keyboard()
    )


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

    photos = acc["photos"][:5]
    if photos:
        media = [InputMediaPhoto(p) for p in photos]
        try:
            bot.send_media_group(call.message.chat.id, media)
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
        f"👨‍💻 {username} ထံ ဆက်သွယ်ပြီး ဝယ်ယူနိုင်ပါတယ်။",
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================================================
# SELL FLOW
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "sell_start")
def sell_start(call):
    bot.answer_callback_query(call.id)

    set_state(call.from_user.id, {
        "flow": "sell_photos",
        "photos": []
    })

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✅ ဓာတ်ပုံအကုန်ပို့ပြီးပြီ", callback_data="sell_photos_done"),
        InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")
    )

    bot.send_message(
        call.message.chat.id,
        "💰 <b>အကောင့်ရောင်းမည်</b>\n\n"
        "📸 အဆင့် (၁)\n"
        "အကောင့်ရဲ့ ပုံတွေကို တစ်ပုံချင်း ပို့ပါ။\n"
        "ပုံအကုန်ပို့ပြီးရင် <b>ဓာတ်ပုံအကုန်ပို့ပြီးပြီ</b> ကိုနှိပ်ပါ။",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(content_types=["photo"])
def receive_photo_message(message):
    user_id = message.from_user.id
    state = get_state(user_id)

    if state.get("flow") == "sell_photos":
        photos = state.get("photos", [])
        photos.append(message.photo[-1].file_id)
        state["photos"] = photos
        set_state(user_id, state)

        bot.send_message(
            user_id,
            f"📸 ပုံ {len(photos)} ပုံ ရရှိပါပြီ။\n"
            "နောက်ထပ်ပုံရှိရင် ဆက်ပို့ပါ။ အကုန်ပြီးရင် အောက်က Button ကိုနှိပ်ပါ။",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ပုံအကုန်ပြီးပြီ", callback_data="sell_photos_done")],
                [InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")]
            ])
        )


@bot.callback_query_handler(func=lambda c: c.data == "sell_photos_done")
def sell_photos_done(call):
    bot.answer_callback_query(call.id)
    state = get_state(call.from_user.id)
    photos = state.get("photos", [])

    if not photos:
        bot.send_message(
            call.message.chat.id,
            "⚠️ ပုံမရသေးပါ။ အရင်ဆုံး အကောင့်ပုံ ပို့ပေးပါ။"
        )
        return

    set_state(call.from_user.id, {
        **state,
        "flow": "sell_error"
    })

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🟢 Error / Issue မရှိ", callback_data="sell_error_none"),
        InlineKeyboardButton("🟡 Error နည်းနည်းရှိ", callback_data="sell_error_minor"),
        InlineKeyboardButton("🔴 Ban / Issue ထိဖူး", callback_data="sell_error_major"),
        InlineKeyboardButton("🔙 ပင်မ Menu", callback_data="home")
    )

    bot.send_message(
        call.message.chat.id,
        "⚠️ <b>အဆင့် (၂)</b>\n\n"
        "ဒီအကောင့်မှာ Error / Ban / Issue ရှိမရှိ ရွေးပါ။",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("sell_error_"))
def sell_error(call):
    bot.answer_callback_query(call.id)

    error_map = {
        "sell_error_none": "Error / Issue မရှိ (Clean)",
        "sell_error_minor": "Error အနည်းငယ်ရှိ",
        "sell_error_major": "Ban / Issue ထိဖူး",
    }

    state = get_state(call.from_user.id)
    state["error_info"] = error_map.get(call.data, "မသိရှိပါ")
    state["flow"] = "sell_price"
    set_state(call.from_user.id, state)

    bot.send_message(
        call.message.chat.id,
        "💵 <b>အဆင့် (၃)</b>\n\n"
        "သင် <b>လိုချင်တဲ့ ရောင်းဈေးအတိအကျ</b> ကို ဂဏန်းနဲ့ ရိုက်ထည့်ပါ။\n\n"
        "ဥပမာ: <b>150000</b> သို့မဟုတ် <b>150,000</b>\n\n"
        "⚠️ ဈေးနှုန်းရွေးစရာ Button ၄ ခု မရှိပါ။ ကိုယ်လိုချင်တဲ့ဈေးကို ကိုယ်တိုင်ရိုက်ထည့်ရမှာပါ။",
        parse_mode="HTML",
        reply_markup=back_button()
    )

    msg = bot.send_message(
        call.message.chat.id,
        "⌨️ <b>ရောင်းလိုဈေးကို အခု ရိုက်ထည့်ပါ</b>",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, receive_sell_price)


def receive_sell_price(message):
    user_id = message.from_user.id
    if not message.text:
        bot.send_message(user_id, "⚠️ ဈေးနှုန်းကို ဂဏန်းနဲ့ ရိုက်ထည့်ပါ။")
        return

    try:
        price = int(message.text.replace(",", "").replace(" ", "").strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(
            user_id,
            "❌ ဈေးနှုန်းမမှန်ပါ။ ဥပမာ <b>150000</b> လို့ ရိုက်ပါ။",
            parse_mode="HTML"
        )
        return

    state = get_state(user_id)
    state["expected_price"] = price
    state["flow"] = "sell_done"
    set_state(user_id, state)

    username = message.from_user.username or "No Username"
    photos = state.get("photos", [])
    error_info = state.get("error_info", "N/A")

    admin_text = (
        "📥 <b>အကောင့်လာရောင်းသူ ရှိပါသည်</b>\n\n"
        f"👤 Username: @{username}\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"⚠️ Error / Issue: {error_info}\n"
        f"💵 ရောင်းလိုဈေး: <b>{price:,} MMK</b>\n"
        f"📸 ပုံအရေအတွက်: {len(photos)} ပုံ"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ လက်ခံမည်", callback_data=f"seller_accept_{user_id}"),
        InlineKeyboardButton("❌ ငြင်းပယ်မည်", callback_data=f"seller_reject_{user_id}")
    )

    try:
        bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML",
            reply_markup=markup
        )

        if photos:
            media = [InputMediaPhoto(p) for p in photos[:30]]
            bot.send_media_group(ADMIN_ID, media)

        bot.send_message(
            user_id,
            "✅ သင့်အကောင့်အချက်အလက်တွေ Admin ဆီကို ပို့ပြီးပါပြီ။\n"
            "Admin က စစ်ဆေးပြီး ပြန်လည်ဆက်သွယ်ပါမယ်။"
        )
    except Exception:
        logging.exception("Failed to notify admin")
        bot.send_message(
            user_id,
            "⚠️ Admin ဆီပို့ရာမှာ ခဏအခက်အခဲရှိပါတယ်။ နောက်တစ်ကြိမ် ပြန်ကြိုးစားပါ။"
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith("seller_accept_"))
def seller_accept(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Accepted")
    user_id = int(call.data.replace("seller_accept_", ""))

    bot.send_message(
        ADMIN_ID,
        f"✅ User <code>{user_id}</code> ရဲ့ ရောင်းရန်တင်ထားတဲ့ Account ကို လက်ခံထားပါတယ်။",
        parse_mode="HTML"
    )
    bot.send_message(
        user_id,
        "✅ Admin က သင့်အကောင့်ရောင်းရန်တင်ထားတာကို လက်ခံထားပါတယ်။"
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("seller_reject_"))
def seller_reject(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Rejected")
    user_id = int(call.data.replace("seller_reject_", ""))

    bot.send_message(
        ADMIN_ID,
        f"❌ User <code>{user_id}</code> ရဲ့ ရောင်းရန်တင်ထားတဲ့ Account ကို ငြင်းပယ်ထားပါတယ်။",
        parse_mode="HTML"
    )
    bot.send_message(
        user_id,
        "❌ Admin က သင့်အကောင့်ရောင်းရန်တင်ထားတာကို လက်ရှိမှာ ငြင်းပယ်ထားပါတယ်။"
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
        "➕ <b>အကောင့်အသစ်တင်ရန်</b>\n\n"
        "ဒီ Format အတိုင်း တစ်ကြောင်းတည်း ရိုက်ပါ:\n\n"
        "<code>Account Name | Skin Type | Price</code>\n\n"
        "ဥပမာ:\n"
        "<code>MLBB Collector | Collector | 150000</code>",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, process_admin_info)


def process_admin_info(message):
    if message.from_user.id != ADMIN_ID:
        return

    if not message.text:
        bot.send_message(ADMIN_ID, "⚠️ စာသားနဲ့ Format အတိုင်း ပြန်ပို့ပါ။")
        return

    parts = [x.strip() for x in message.text.split("|")]

    if len(parts) != 3:
        bot.send_message(
            ADMIN_ID,
            "❌ Format မှားနေပါတယ်။\n\n"
            "<code>Account Name | Skin Type | Price</code>",
            parse_mode="HTML"
        )
        return

    title, skins, price_text = parts

    try:
        price = int(price_text.replace(",", "").replace(" ", ""))
        if price <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Price က ဂဏန်းဖြစ်ရပါမယ်။")
        return

    account_number = next_account_number()
    account_id = make_account_id(account_number)

    set_state(ADMIN_ID, {
        "flow": "admin_photos",
        "id": account_id,
        "db_id": account_number,
        "title": title,
        "skins": skins,
        "price": price,
        "photos": []
    })

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✅ ပုံအကုန်တင်ပြီးပြီ", callback_data="admin_save"),
        InlineKeyboardButton("❌ မသိမ်းဘူး", callback_data="admin_cancel")
    )

    bot.send_message(
        ADMIN_ID,
        f"📸 <b>{account_id}</b>\n\n"
        "အကောင့်ရဲ့ <b>မူရင်းပုံအစစ်</b> တွေကို ပို့ပါ။\n"
        "အများဆုံး ၅ ပုံ ပြသပါမယ်။\n\n"
        "ပုံအကုန်ပို့ပြီးရင် Button ကိုနှိပ်ပါ။",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_save")
def admin_save(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    state = get_state(ADMIN_ID)

    if state.get("flow") != "admin_photos":
        bot.send_message(ADMIN_ID, "❌ Save လုပ်မယ့် data မရှိပါ။ /admin ကနေ ပြန်စပါ။")
        return

    photos = state.get("photos", [])
    if not photos:
        bot.send_message(ADMIN_ID, "⚠️ Account ပုံ အနည်းဆုံး ၁ ပုံ ပို့ပေးပါ။")
        return

    # We reserved the ID number in settings. Insert with that exact ID.
    with db_lock:
        with closing(db_connect()) as conn:
            conn.execute("""
                INSERT INTO accounts(id, title, skins, price, photos, status)
                VALUES(?, ?, ?, ?, ?, 'available')
            """, (
                state["db_id"],
                state["title"],
                state["skins"],
                state["price"],
                ",".join(photos[:10])
            ))
            conn.commit()

    clear_state(ADMIN_ID)

    bot.send_message(
        ADMIN_ID,
        f"🎉 <b>{state['id']}</b> ကို Database ထဲမှာ ရေရှည်သိမ်းပြီးပါပြီ။\n\n"
        f"📝 {state['title']}\n"
        f"✨ {state['skins']}\n"
        f"💵 {state['price']:,} MMK\n"
        f"📸 {len(photos[:10])} ပုံ",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_cancel")
def admin_cancel(call):
    if call.from_user.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    clear_state(ADMIN_ID)
    bot.send_message(
        ADMIN_ID,
        "❌ မသိမ်းတော့ပါ။",
        reply_markup=admin_keyboard()
    )


@bot.message_handler(content_types=["photo"])
def receive_admin_photo(message):
    if message.from_user.id != ADMIN_ID:
        return

    state = get_state(ADMIN_ID)
    if state.get("flow") != "admin_photos":
        return

    photos = state.get("photos", [])
    if len(photos) >= 10:
        bot.send_message(ADMIN_ID, "⚠️ အများဆုံး ၁၀ ပုံပဲ သိမ်းထားပါတယ်။")
        return

    photos.append(message.photo[-1].file_id)
    state["photos"] = photos
    set_state(ADMIN_ID, state)

    bot.send_message(
        ADMIN_ID,
        f"📸 ပုံ {len(photos)} ပုံ ရရှိပါပြီ။\n"
        "နောက်ထပ်ရှိရင် ဆက်ပို့ပါ။ ပြီးရင် <b>ပုံအကုန်တင်ပြီးပြီ</b> ကိုနှိပ်ပါ။",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ ပုံအကုန်တင်ပြီးပြီ", callback_data="admin_save")],
            [InlineKeyboardButton("❌ မသိမ်းဘူး", callback_data="admin_cancel")]
        ])
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_list")
def admin_list(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    accounts = get_available_accounts()

    if not accounts:
        bot.send_message(
            ADMIN_ID,
            "📂 လက်ကျန် Account မရှိသေးပါ။",
            reply_markup=admin_keyboard()
        )
        return

    bot.send_message(
        ADMIN_ID,
        f"📊 <b>လက်ကျန် Account = {len(accounts)} ခု</b>",
        parse_mode="HTML"
    )

    for acc in accounts:
        bot.send_message(
            ADMIN_ID,
            format_account(acc),
            parse_mode="HTML"
        )


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

    # next_step_handler normally handles active text input first.
    # This is only a friendly fallback.
    if state.get("flow") == "sell_price":
        return
    if state.get("flow") == "admin_info":
        return
    if state.get("flow") in ("buy_skin_custom", "buy_budget_custom"):
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
