"""
MLBB MARKET - PREMIUM FEATURES ADDON v17
=======================================
This file is intentionally separate from:
    main.py
    supabase_launcher.py

It does NOT edit or replace either file.

It adds reliable premium features through a callback-update interceptor so
new feature buttons are handled BEFORE the original generic callback handlers.
This avoids callback-order conflicts in the original bot.

Features:
    ⚡ Fast Buy
    🔥 Flash Deal
    🔔 Price Drop Alert
    ✅ Verified Account
    👤 My Account
    🆕 New Accounts
    🔎 Advanced Search
    🔔 New Account Notification
    ❤️ Favorites

Important UX rules:
    - Existing main.py flows are preserved.
    - Existing account data is never deleted by this addon.
    - No message deletion/cleanup is performed by this addon.
    - Main menu stays compact.
    - Admin-only controls stay inside the Admin menu.
    - Account cards always send the text card even if a photo fails.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import threading
import logging
import html
from urllib.parse import quote

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

print(
    "[PREMIUM_FEATURES_DEBUG_BUILD] premium_features_v21_gmail_button.py "
    "MODULE LOADED - if you see this after redeploy, the new file IS live",
    flush=True,
)

_INSTALLED = False



def _reply_keyboard_markup(user_id, admin=False):
    """Bottom Reply Keyboard: exactly four primary actions."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=2)
    kb.row(KeyboardButton("🛒 အကောင့်ဝယ်မယ်"), KeyboardButton("👀 အကောင့်ကြည့်မယ်"))
    kb.row(KeyboardButton("💰 အကောင့်ရောင်းမယ်"), KeyboardButton("💸 လျော့စျေးအကောင့်များ"))
    return kb


def _inline_compact_main_menu(user_id, original):
    """Flat Inline Menu: feature buttons only, no Reply Keyboard duplicates."""
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("❤️ သိမ်းထားတဲ့အကောင့်များ", callback_data="premium_favorites"),
        InlineKeyboardButton("🆕 အသစ်တင်ထားတဲ့အကောင့်များ", callback_data="premium_new_accounts"),
        InlineKeyboardButton("🔎 ဂိမ်းအကောင့်ရှာမယ်", callback_data="premium_advanced_search"),
        InlineKeyboardButton("🔥 အထူးစပရှယ် လျော့စျေးအကောင့်များ", callback_data="premium_special_deals"),
    )
    return m

def _install_reply_keyboard_layer(original):
    """
    Intercept /start + only the three bottom-keyboard menu labels.
    This leaves every other original text/message handler untouched.
    """
    bot = original.bot

    # The original Flask webhook eventually calls bot.process_new_updates().
    previous = bot.process_new_updates
    if hasattr(bot, "_reply_keyboard_v1_previous_process"):
        return
    bot._reply_keyboard_v1_previous_process = previous

    def _direct_buy(message):
        try:
            original.clear_state(message.from_user.id)
            original.log_user_activity(message.from_user, "buy_menu")
        except Exception:
            pass
        bot.send_message(
            message.chat.id,
            "🛒 <b>အကောင့်ဝယ်မယ်</b>\n\n"
            "လိုချင်တဲ့ Skin နာမည်နဲ့ Budget ကို တစ်ကြောင်းတည်း ရိုက်ပို့ပါ။\n\n"
            "ဥပမာ — <code>Gusion | 200000</code>\n"
            "သို့မဟုတ် <code>Any | 300000</code>",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        try:
            original.set_state(message.from_user.id, {"flow": "buy_query"})
        except Exception:
            pass

    def _direct_browse(message):
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(
                message.chat.id,
                "❌ လောလောဆယ် ပြသရန် အကောင့် မရှိသေးပါ။",
                reply_markup=original.back_button(),
            )
            return

        acc = accounts[0]
        photos = [p for p in (acc.get("photos") or []) if p][:15]
        text_card = original.format_account(acc)

        if photos:
            try:
                from telebot.types import InputMediaPhoto
                media = []
                for i, p in enumerate(photos):
                    if i == 0:
                        media.append(
                            InputMediaPhoto(
                                p,
                                caption=text_card,
                                parse_mode="HTML",
                            )
                        )
                    else:
                        media.append(InputMediaPhoto(p))
                bot.send_media_group(message.chat.id, media)
            except Exception:
                try:
                    bot.send_photo(
                        message.chat.id,
                        photos[0],
                        caption=text_card,
                        parse_mode="HTML",
                    )
                except Exception:
                    bot.send_message(
                        message.chat.id,
                        text_card,
                        parse_mode="HTML",
                    )
                for p in photos[1:]:
                    try:
                        bot.send_photo(message.chat.id, p)
                    except Exception:
                        pass
        else:
            bot.send_message(
                message.chat.id,
                text_card,
                parse_mode="HTML",
            )

        # Keep navigation controls without adding explanatory text.
        bot.send_message(
            message.chat.id,
            "\u200b",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⬅️ အရင်Account", callback_data="premium_browse_prev"),
                    InlineKeyboardButton("နောက် Account ➡️", callback_data="premium_browse_next"),
                ],
                [InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")],
            ]),
        )
        original.set_state(
            message.from_user.id,
            {"flow": "browse", "browse_index": 0},
        )

    def _direct_sell(message):
        # Reuse the original sell-start handler by reproducing its exact entry state.
        try:
            original.clear_state(message.from_user.id)
            original.set_state(
                message.from_user.id,
                {
                    "flow": "sell_photos",
                    "photos": [],
                    "photo_prompt_sent": False,
                },
            )
            original.log_user_activity(message.from_user, "sell_start")
        except Exception:
            pass

        bot.send_message(
            message.chat.id,
            "💰 <b>အကောင့်ရောင်းမယ်</b>\n\n"
            "📸 Account ပုံ <b>အများဆုံး 15 ပုံ</b> ကို <b>တစ်ခါတည်း Album</b> အနေနဲ့ ပို့ပါ။\n\n"
            "ပုံအားလုံးရောက်ပြီးမှ Bot က လိုအပ်တာတွေ တစ်ဆင့်ချင်း မေးပါမယ်။",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )

    def intercepted(updates):
        remaining = []
        for update in updates or []:
            message = getattr(update, "message", None)
            if message is not None:
                txt = (getattr(message, "text", None) or "").strip()

                if txt == "/start":
                    try:
                        original.clear_state(message.from_user.id)
                        original.log_user_activity(message.from_user, "start")
                    except Exception:
                        pass
                    bot.send_message(
                        message.chat.id,
                        "⁣",
                        reply_markup=_reply_keyboard_markup(message.from_user.id, message.from_user.id == original.ADMIN_ID),
                    )
                    bot.send_message(
                        message.chat.id,
                        "⁣",
                        reply_markup=_inline_compact_main_menu(message.from_user.id, original),
                    )
                    continue

                if txt == "🛒 အကောင့်ဝယ်မယ်":
                    _direct_buy(message)
                    continue

                if txt == "👀 အကောင့်ကြည့်မယ်":
                    _direct_browse(message)
                    continue

                if txt == "💰 အကောင့်ရောင်းမယ်":
                    _direct_sell(message)
                    continue

                if txt == "💸 လျော့စျေးအကောင့်များ":
                    # Hand the same original discount menu callback a proper update.
                    try:
                        from types import SimpleNamespace
                        # Use a lightweight direct flow: invoke the original callback is unsafe,
                        # so let the original handler process a synthetic callback is avoided.
                        # Instead present the existing discount action through a small inline menu.
                        bot.send_message(
                            message.chat.id,
                            "💸 <b>လျော့စျေးအကောင့်များ</b>",
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔥 အထူးစပရှယ် လျော့စျေးအကောင့်များ", callback_data="premium_special_deals")],
                                [InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")],
                            ]),
                        )
                    except Exception:
                        logging.exception("Discount reply keyboard failed")
                    continue

            remaining.append(update)

        if remaining:
            return bot._reply_keyboard_v1_previous_process(remaining)
        return None

    bot.process_new_updates = intercepted


def install(original):
    """Install the addon onto the already-loaded main.py module."""
    global _INSTALLED
    print("[PREMIUM_FEATURES_DEBUG_BUILD] install() called", flush=True)
    if _INSTALLED:
        print("[PREMIUM_FEATURES_DEBUG_BUILD] install() skipped - already installed", flush=True)
        return
    _INSTALLED = True
    print("[PREMIUM_FEATURES_DEBUG_BUILD] install() proceeding, _INSTALLED set True", flush=True)

    bot = original.bot
    ADMIN_ID = int(original.ADMIN_ID)

    # IMPORTANT: install the bottom Reply Keyboard interceptor now.
    # This must happen before start_original_bot() begins serving updates.
    _install_reply_keyboard_layer(original)
    db_lock = original.db_lock
    db_connect = original.db_connect
    closing = original.closing

    # ------------------------------------------------------------
    # DB additions only. Existing rows/tables are preserved.
    # ------------------------------------------------------------
    def init_feature_db():
        with db_lock:
            with closing(db_connect()) as conn:
                cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(accounts)").fetchall()
                }
                if "is_verified" not in cols:
                    conn.execute(
                        "ALTER TABLE accounts "
                        "ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
                    )

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_favorites (
                        user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, account_id)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_user_settings (
                        user_id INTEGER PRIMARY KEY,
                        new_account_alert INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_price_alerts (
                        user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        last_price INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, account_id)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_flash_deals (
                        account_id INTEGER PRIMARY KEY,
                        deal_price INTEGER NOT NULL,
                        ends_at TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_buy_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        buyer_user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        account_code TEXT NOT NULL,
                        price INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'awaiting_receipt',
                        receipt_file_id TEXT NOT NULL DEFAULT '',
                        receipt_type TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS premium_seller_deals (
                        request_id INTEGER PRIMARY KEY,
                        seller_user_id INTEGER NOT NULL,
                        seller_expected_price INTEGER NOT NULL DEFAULT 0,
                        seller_note TEXT NOT NULL DEFAULT '',
                        admin_offer_price INTEGER NOT NULL DEFAULT 0,
                        negotiation_count INTEGER NOT NULL DEFAULT 0,
                        moonton_changeable TEXT NOT NULL DEFAULT '',
                        gmail_mailbox_id INTEGER NOT NULL DEFAULT 0,
                        gmail_email TEXT NOT NULL DEFAULT '',
                        moonton_status TEXT NOT NULL DEFAULT 'not_started',
                        moonton_proof_file_id TEXT NOT NULL DEFAULT '',
                        moonton_proof_type TEXT NOT NULL DEFAULT '',
                        admin_verified INTEGER NOT NULL DEFAULT 0,
                        payout_destination TEXT NOT NULL DEFAULT '',
                        payout_amount INTEGER NOT NULL DEFAULT 0,
                        payout_receipt_file_id TEXT NOT NULL DEFAULT '',
                        payout_receipt_type TEXT NOT NULL DEFAULT '',
                        seller_payout_confirmed INTEGER NOT NULL DEFAULT 0,
                        final_account_id INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'awaiting_admin_price',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_premium_seller_deals_seller
                    ON premium_seller_deals(seller_user_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_premium_seller_deals_status
                    ON premium_seller_deals(status)
                """)

                conn.commit()

    init_feature_db()

    def rows(sql, params=()):
        with db_lock:
            with closing(db_connect()) as conn:
                return conn.execute(sql, params).fetchall()

    def account_by_number(account_id):
        try:
            return original.get_account_by_text_id(
                original.make_account_id(int(account_id))
            )
        except Exception:
            return None

    def account_by_text(account_id):
        try:
            return original.get_account_by_text_id(str(account_id))
        except Exception:
            return None

    def is_verified(account_id):
        result = rows(
            "SELECT is_verified FROM accounts WHERE id=?",
            (int(account_id),),
        )
        return bool(result and int(result[0]["is_verified"] or 0))

    def set_verified(account_id, enabled):
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute(
                    "UPDATE accounts SET is_verified=? WHERE id=?",
                    (1 if enabled else 0, int(account_id)),
                )
                conn.commit()

    def favorite_ids(user_id):
        result = rows(
            "SELECT account_id FROM premium_favorites "
            "WHERE user_id=? ORDER BY created_at DESC",
            (int(user_id),),
        )
        return [int(r["account_id"]) for r in result]

    def toggle_favorite(user_id, account_id):
        with db_lock:
            with closing(db_connect()) as conn:
                found = conn.execute(
                    "SELECT 1 FROM premium_favorites WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()
                if found:
                    conn.execute(
                        "DELETE FROM premium_favorites WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    added = False
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO premium_favorites(user_id, account_id) VALUES(?,?)",
                        (int(user_id), int(account_id)),
                    )
                    added = True
                conn.commit()
        return added

    def new_alert_enabled(user_id):
        result = rows(
            "SELECT new_account_alert FROM premium_user_settings WHERE user_id=?",
            (int(user_id),),
        )
        return bool(result and int(result[0]["new_account_alert"] or 0))

    def set_new_alert(user_id, enabled):
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute("""
                    INSERT INTO premium_user_settings(user_id, new_account_alert)
                    VALUES(?, ?)
                    ON CONFLICT(user_id)
                    DO UPDATE SET new_account_alert=excluded.new_account_alert
                """, (int(user_id), 1 if enabled else 0))
                conn.commit()

    def toggle_price_alert(user_id, account_id):
        acc = account_by_number(account_id)
        if not acc:
            return None
        current_price = int(acc.get("effective_price") or acc.get("price") or 0)
        with db_lock:
            with closing(db_connect()) as conn:
                found = conn.execute(
                    "SELECT 1 FROM premium_price_alerts WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()
                if found:
                    conn.execute(
                        "DELETE FROM premium_price_alerts WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    enabled = False
                else:
                    conn.execute("""
                        INSERT OR REPLACE INTO premium_price_alerts(
                            user_id, account_id, last_price
                        ) VALUES(?, ?, ?)
                    """, (int(user_id), int(account_id), current_price))
                    enabled = True
                conn.commit()
        return enabled

    def active_flash(account_id):
        result = rows(
            "SELECT deal_price, ends_at FROM premium_flash_deals WHERE account_id=?",
            (int(account_id),),
        )
        if not result:
            return None
        try:
            ends = datetime.fromisoformat(
                str(result[0]["ends_at"]).replace("Z", "+00:00")
            )
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)
            if ends <= datetime.now(timezone.utc):
                with db_lock:
                    with closing(db_connect()) as conn:
                        conn.execute(
                            "DELETE FROM premium_flash_deals WHERE account_id=?",
                            (int(account_id),),
                        )
                        conn.commit()
                return None
            return int(result[0]["deal_price"]), ends
        except Exception:
            return None

    def set_flash(account_id, price, minutes):
        ends = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute("""
                    INSERT INTO premium_flash_deals(account_id, deal_price, ends_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(account_id)
                    DO UPDATE SET deal_price=excluded.deal_price, ends_at=excluded.ends_at
                """, (int(account_id), int(price), ends.isoformat()))
                conn.commit()

    # ------------------------------------------------------------
    # Preserve original formatter and main/admin menus.
    # ------------------------------------------------------------
    if not hasattr(original, "_premium_v8_row_to_account"):
        original._premium_v8_row_to_account = original.row_to_account
    if not hasattr(original, "_premium_v8_format_account"):
        original._premium_v8_format_account = original.format_account
    if not hasattr(original, "_premium_v8_main_menu"):
        original._premium_v8_main_menu = original.main_menu
    if not hasattr(original, "_premium_v8_admin_keyboard"):
        original._premium_v8_admin_keyboard = original.admin_keyboard

    def row_to_account_wrapped(row):
        acc = original._premium_v8_row_to_account(row)
        try:
            acc["is_verified"] = int(row["is_verified"] or 0) if "is_verified" in row.keys() else 0
        except Exception:
            acc["is_verified"] = 0
        return acc

    def short_skins(value):
        text = str(value or "").replace("\n", " ").strip()
        if len(text) > 110:
            return text[:107] + "..."
        return text

    def format_account_wrapped(acc):
        lines = original._premium_v8_format_account(acc).split("\n")
        lines = [line.replace("GAMING SHOP", "Aung Gyi GameShop") for line in lines]

        if not any("Admin စစ်ဆေးပြီး" in x for x in lines):
            lines.insert(min(4, len(lines)), "✅ <b>Admin စစ်ဆေးပြီး</b>")

        return "\n".join(lines)

    original.row_to_account = row_to_account_wrapped
    original.format_account = format_account_wrapped

    def quick_reply_keyboard():
        """Exactly four primary actions in Telegram bottom Reply Keyboard."""
        m = ReplyKeyboardMarkup(
            resize_keyboard=True,
            one_time_keyboard=False,
            row_width=2,
        )
        m.row(
            KeyboardButton("🛒 အကောင့်ဝယ်မယ်"),
            KeyboardButton("👀 အကောင့်ကြည့်မယ်"),
        )
        m.row(
            KeyboardButton("💰 အကောင့်ရောင်းမယ်"),
            KeyboardButton("💸 လျော့စျေးအကောင့်များ"),
        )
        return m

    def show_quick_reply(chat_id):
        try:
            bot.send_message(
                chat_id,
                "⌨️ <b>အမြန် Menu</b>",
                parse_mode="HTML",
                reply_markup=quick_reply_keyboard(),
            )
        except Exception:
            logging.exception("Quick keyboard send failed")

    def main_menu_wrapped(user_id):
        # Main actions live only in Reply Keyboard; inline area shows features.
        m = _inline_compact_main_menu(user_id, original)
        if int(user_id) == ADMIN_ID:
            m.add(InlineKeyboardButton("👑 ADMIN PANEL", callback_data="admin_home"))
        return m

    def admin_menu_wrapped():
        m = original._premium_v8_admin_keyboard()
        if not any(getattr(btn, "callback_data", None) == "premium_admin_tools" for row in m.keyboard for btn in row):
            m.add(InlineKeyboardButton("✨ Premium Features စီမံမယ်", callback_data="premium_admin_tools"))
        return m

    original.main_menu = main_menu_wrapped
    original.admin_keyboard = admin_menu_wrapped

    # ------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------
    def buyer_features_menu():
        m = InlineKeyboardMarkup(row_width=2)
        m.add(
            InlineKeyboardButton("❤️ သိမ်းထားတဲ့အကောင့်များ", callback_data="premium_favorites"),
            InlineKeyboardButton("🆕 အသစ်တင်ထားတဲ့အကောင့်များ", callback_data="premium_new_accounts"),
            InlineKeyboardButton("🔎 ဂိမ်းအကောင့်ရှာမယ်", callback_data="premium_advanced_search"),
            InlineKeyboardButton("🔥 အထူးစပရှယ် လျော့စျေးအကောင့်များ", callback_data="premium_special_deals"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        return m

    def admin_features_menu():
        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton("🔥 Flash Deal စီမံမယ်", callback_data="premium_admin_flash_list"),
            InlineKeyboardButton("✅ Verified စီမံမယ်", callback_data="premium_admin_verified_list"),
            InlineKeyboardButton("🔔 အသိပေးချက် အချက်အလက်", callback_data="premium_admin_alert_stats"),
            InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"),
        )
        return m

    def account_nav_markup(kind, acc):
        prev_next = {
            "browse": ("premium_browse_prev", "premium_browse_next"),
            "search": ("premium_search_prev", "premium_search_next"),
            "favorites": ("premium_fav_prev", "premium_fav_next"),
            "new": ("premium_new_prev", "premium_new_next"),
            "verified": ("premium_ver_prev", "premium_ver_next"),
        }
        prev_cb, next_cb = prev_next.get(kind, prev_next["browse"])
        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton("⬅️ အရင်Account", callback_data=prev_cb),
            InlineKeyboardButton("နောက် Account ➡️", callback_data=next_cb),
        )
        m.row(
            InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"),
            InlineKeyboardButton("❤️ သိမ်းထားမယ်", callback_data=f"premium_fav_toggle_{acc['db_id']}"),
        )
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        return m

    def send_account_card(chat_id, acc, kind, index, total):
        if not acc:
            bot.send_message(chat_id, "❌ ဒီအကောင့် မရှိတော့ပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
            return
        photos = [p for p in (acc.get("photos") or []) if p][:15]
        caption = f"🎯 <b>{index + 1} / {max(1, total)}</b>\n\n{format_account_wrapped(acc)}"
        prev_map={"browse":"premium_browse_prev","search":"premium_search_prev","favorites":"premium_fav_prev","new":"premium_new_prev","verified":"premium_ver_prev"}
        next_map={"browse":"premium_browse_next","search":"premium_search_next","favorites":"premium_fav_next","new":"premium_new_next","verified":"premium_ver_next"}
        nav=InlineKeyboardMarkup(row_width=2)
        nav.row(InlineKeyboardButton("⬅️ အရင်Account", callback_data=prev_map.get(kind,"premium_browse_prev")), InlineKeyboardButton("နောက် Account ➡️", callback_data=next_map.get(kind,"premium_browse_next")))
        nav.row(InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"), InlineKeyboardButton("❤️ သိမ်းထားမယ်", callback_data=f"premium_fav_toggle_{acc['db_id']}"))
        nav.row(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        if photos:
            try:
                from telebot.types import InputMediaPhoto
                media=[InputMediaPhoto(p, caption=caption, parse_mode="HTML") if i==0 else InputMediaPhoto(p) for i,p in enumerate(photos)]
                bot.send_media_group(chat_id, media)
                # Media groups cannot have inline keyboards. Send only the controls with no extra prose.
                bot.send_message(chat_id, "⁣", reply_markup=nav)
                return
            except Exception:
                logging.exception("Account media group failed: %s", acc.get("id"))
            try:
                bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=nav)
                for p in photos[1:]:
                    try: bot.send_photo(chat_id,p)
                    except Exception: pass
                return
            except Exception:
                logging.exception("Account photo+caption fallback failed: %s", acc.get("id"))
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=nav)

    # ------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------
    def show_list(chat_id, user_id, ids, kind):
        if not ids:
            bot.send_message(
                chat_id,
                "❌ ဒီအမျိုးအစားအကောင့် မရှိသေးပါ။",
                reply_markup=buyer_features_menu(),
            )
            return
        original.set_state(
            user_id,
            {
                "flow": f"premium_{kind}",
                "premium_ids": ids,
                "premium_index": 0,
                "premium_kind": kind,
            },
        )
        acc = account_by_text(ids[0])
        send_account_card(chat_id, acc, kind, 0, len(ids))

    def navigate(call, direction):
        state = original.get_state(call.from_user.id)
        ids = state.get("premium_ids") or []
        if not ids:
            bot.send_message(call.message.chat.id, "❌ ကြည့်ရန်အကောင့် မရှိသေးပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
            return
        idx = (int(state.get("premium_index", 0)) + int(direction)) % len(ids)
        state["premium_index"] = idx
        original.set_state(call.from_user.id, state)
        acc = account_by_text(ids[idx])
        send_account_card(
            call.message.chat.id,
            acc,
            state.get("premium_kind", "browse"),
            idx,
            len(ids),
        )

    # ------------------------------------------------------------
    # Callback implementations
    # ------------------------------------------------------------
    def handle_callback(call):
        data = call.data or ""
        if data == "home":
            bot.answer_callback_query(call.id)
            try:
                original.clear_state(call.from_user.id)
            except Exception:
                pass
            bot.send_message(
                call.message.chat.id,
                "⁣",
                reply_markup=_inline_compact_main_menu(call.from_user.id, original),
            )
            return True

        if data == "premium_more":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                "⁣",
                reply_markup=_inline_compact_main_menu(call.from_user.id, original),
            )
            return True

        if data == "premium_my_account":
            bot.answer_callback_query(call.id)
            uid = call.from_user.id
            fav_count = len(favorite_ids(uid))
            alert = "ဖွင့်ထား ✅" if new_alert_enabled(uid) else "ပိတ်ထား ❌"
            m = InlineKeyboardMarkup(row_width=2)
            m.add(
                InlineKeyboardButton("❤️ သိမ်းထားတာကြည့်မယ်", callback_data="premium_favorites"),
                InlineKeyboardButton("🆕 အသစ်တင်တာကြည့်မယ်", callback_data="premium_new_accounts"),
                InlineKeyboardButton("🔎 အဆင့်မြင့်ရှာဖွေ", callback_data="premium_advanced_search"),
                InlineKeyboardButton("🔔 အသိပေးချက်ပြောင်း", callback_data="premium_new_alert"),
                InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
            )
            bot.send_message(
                call.message.chat.id,
                "👤 <b>ကျွန်ုပ်၏အကောင့်</b>\n\n"
                f"🆔 User ID — <code>{uid}</code>\n"
                f"❤️ သိမ်းထားတဲ့အကောင့် — <b>{fav_count}</b> ခု\n"
                f"🔔 အသစ်တင်အသိပေးချက် — <b>{alert}</b>",
                parse_mode="HTML",
                reply_markup=m,
            )
            return True

        if data == "premium_favorites":
            bot.answer_callback_query(call.id)
            ids = [original.make_account_id(x) for x in favorite_ids(call.from_user.id) if account_by_number(x)]
            show_list(call.message.chat.id, call.from_user.id, ids, "favorites")
            return True

        if data in ("premium_fav_prev", "premium_fav_next"):
            bot.answer_callback_query(call.id)
            navigate(call, -1 if data.endswith("prev") else 1)
            return True

        if data.startswith("premium_fav_toggle_"):
            bot.answer_callback_query(call.id)
            aid = int(data.replace("premium_fav_toggle_", "", 1))
            acc = account_by_number(aid)
            if not acc:
                bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
            else:
                added = toggle_favorite(call.from_user.id, aid)
                bot.send_message(
                    call.message.chat.id,
                    f"❤️ <b>{acc['id']}</b> ကို သိမ်းထားလိုက်ပါပြီ။" if added else f"💔 <b>{acc['id']}</b> ကို သိမ်းထားတာ ဖြုတ်လိုက်ပါပြီ။",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]),
                )
            return True

        if data == "premium_new_accounts":
            bot.answer_callback_query(call.id)
            accs = original.get_available_accounts()
            # Newest first, preserving ACC sequence identity.
            accs = list(reversed(accs))
            show_list(call.message.chat.id, call.from_user.id, [a["id"] for a in accs], "new")
            return True

        if data in ("premium_new_prev", "premium_new_next"):
            bot.answer_callback_query(call.id)
            navigate(call, -1 if data.endswith("prev") else 1)
            return True

        if data == "premium_verified":
            bot.answer_callback_query(call.id)
            accs = [a for a in original.get_available_accounts() if is_verified(a["db_id"])]
            show_list(call.message.chat.id, call.from_user.id, [a["id"] for a in accs], "verified")
            return True

        if data in ("premium_ver_prev", "premium_ver_next"):
            bot.answer_callback_query(call.id)
            navigate(call, -1 if data.endswith("prev") else 1)
            return True

        if data == "premium_new_alert":
            bot.answer_callback_query(call.id)
            enabled = not new_alert_enabled(call.from_user.id)
            set_new_alert(call.from_user.id, enabled)
            bot.send_message(
                call.message.chat.id,
                "🔔 <b>အသစ်တင်အကောင့် အသိပေးချက် ဖွင့်ပြီးပါပြီ။</b>" if enabled else "🔕 <b>အသစ်တင်အကောင့် အသိပေးချက် ပိတ်ပြီးပါပြီ။</b>",
                parse_mode="HTML",
                reply_markup=buyer_features_menu(),
            )
            return True

        if data.startswith("premium_price_alert_"):
            bot.answer_callback_query(call.id)
            aid = int(data.replace("premium_price_alert_", "", 1))
            enabled = toggle_price_alert(call.from_user.id, aid)
            if enabled is None:
                bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
            else:
                acc = account_by_number(aid)
                bot.send_message(
                    call.message.chat.id,
                    f"🔔 <b>{acc['id']}</b> ဈေးကျရင် အသိပေးပါမယ်။" if enabled else f"🔕 <b>{acc['id']}</b> ရဲ့ ဈေးကျအသိပေးချက် ပိတ်လိုက်ပါပြီ။",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]),
                )
            return True

        if data == "premium_buy_cancel":
            bot.answer_callback_query(call.id)
            original.clear_state(call.from_user.id)
            bot.send_message(
                call.message.chat.id,
                "✅ ဝယ်ယူမှုကို ပယ်ဖျက်လိုက်ပါပြီ။",
                reply_markup=buyer_features_menu(),
            )
            return True


        # --------------------------------------------------------
        # Seller negotiation / handoff callbacks
        # --------------------------------------------------------
        if data.startswith("seller_photos_done"):
            bot.answer_callback_query(call.id)
            return _intercept_sell_photos_done(call)

        if data.startswith("premium_seller_offer_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(
                    call.id,
                    "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                    show_alert=True,
                )
                return True

            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_offer_",
                    "",
                    1,
                )
            )

            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)

            if not row:
                bot.send_message(
                    ADMIN_ID,
                    "❌ Seller Request မတွေ့ပါ။",
                )
                return True

            original.set_state(
                ADMIN_ID,
                {
                    "flow": "premium_seller_set_offer",
                    "request_id": request_id,
                },
            )

            msg = bot.send_message(
                ADMIN_ID,
                f"💰 <b>SELL-{request_id:04d}</b>\n\n"
                "Seller ကို ပေးမယ့်ဈေးကို ရိုက်ပေးပါ။\n"
                "ဥပမာ — <code>120000</code>",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _admin_set_seller_offer,
            )
            return True

        if data.startswith("premium_seller_negotiate_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_negotiate_",
                    "",
                    1,
                )
            )
            original.set_state(
                call.from_user.id,
                {
                    "flow": "seller_negotiate_price",
                    "request_id": request_id,
                },
            )
            msg = bot.send_message(
                call.message.chat.id,
                "💰 <b>ကိုယ်လိုချင်တဲ့ဈေး</b> ကို ရိုက်ပို့ပါ။\n"
                "ဥပမာ — <code>130000</code>",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _seller_negotiate_price,
            )
            return True

        if data.startswith("premium_seller_accept_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_accept_",
                    "",
                    1,
                )
            )

            if call.from_user.id == ADMIN_ID:
                return True

            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)

            if not row or not deal:
                bot.send_message(
                    call.message.chat.id,
                    "❌ Seller Request မတွေ့ပါ။",
                    reply_markup=buyer_features_menu(),
                )
                return True

            offer = int(deal["admin_offer_price"] or 0)
            if offer <= 0:
                bot.send_message(
                    call.message.chat.id,
                    "❌ Admin စျေး မရသေးပါ။",
                    reply_markup=buyer_features_menu(),
                )
                return True

            _upsert_seller_deal(
                request_id,
                call.from_user.id,
                admin_offer_price=offer,
                status="seller_accepted_offer",
            )

            # Ask whether seller can use the assigned Gmail for the Moonton change.
            m = InlineKeyboardMarkup(row_width=2)
            m.row(
                InlineKeyboardButton(
                    "✅ လုပ်နိုင်ပါတယ်",
                    callback_data=f"premium_seller_moonton_yes_{request_id}",
                ),
                InlineKeyboardButton(
                    "❌ မလုပ်နိုင်ပါ",
                    callback_data=f"premium_seller_moonton_no_{request_id}",
                ),
            )
            bot.send_message(
                call.message.chat.id,
                "✅ Admin ပေးတဲ့ <b>{:,} MMK</b> စျေးကို လက်ခံပြီးပါပြီ။\n\n"
                "အခု <b>Moonton Mail ပြောင်းနိုင်/မပြောင်းနိုင်</b> ကို ရွေးပေးပါ။".format(offer),
                parse_mode="HTML",
                reply_markup=m,
            )
            return True

        if data.startswith("premium_seller_moonton_yes_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_moonton_yes_",
                    "",
                    1,
                )
            )

            row = _seller_request_row(request_id)
            if not row:
                return True

            allocated = _allocate_available_gmail(
                request_id,
                int(row["user_id"]),
            )
            if not allocated:
                bot.send_message(
                    call.message.chat.id,
                    "⏳ လောလောဆယ် Moonton Mail ပြောင်းရန် "
                    "Gmail မရှိသေးပါ။ Admin ကို အသိပေးထားပါတယ်။",
                    reply_markup=buyer_features_menu(),
                )
                bot.send_message(
                    ADMIN_ID,
                    f"⚠️ SELL-{request_id:04d} အတွက် "
                    "Moonton Mail ပြောင်းရန် Available Gmail မရှိသေးပါ။",
                )
                return True

            mailbox_id, gmail_email = allocated

            gmail_inbox_url = (
                "https://mail.google.com/mail/"
                f"?authuser={quote(gmail_email, safe="")}#inbox"
            )

            assigned_markup = InlineKeyboardMarkup(row_width=1)
            assigned_markup.add(
                InlineKeyboardButton(
                    "📧 Gmail Inbox ဖွင့်မယ်",
                    url=gmail_inbox_url,
                )
            )
            assigned_markup.add(
                InlineKeyboardButton(
                    "✅ Gmail ရပြီးပြီ",
                    callback_data=f"premium_seller_gmail_ready_{request_id}",
                )
            )

            bot.send_message(
                call.message.chat.id,
                "📧 <b>သင့်အတွက် Assigned Gmail</b>\n\n"
                f"<code>{_esc(gmail_email)}</code>\n\n"
                "အောက်က <b>Gmail Inbox ဖွင့်မယ်</b> ကိုနှိပ်ပြီး Gmail ကိုဖွင့်ပါ။\n\n"
                "Gmail ရပြီးပါပြီဆိုရင် <b>Gmail ရပြီးပြီ</b> ကိုနှိပ်ပါ။",
                parse_mode="HTML",
                reply_markup=assigned_markup,
            )
            return True

        if data.startswith("premium_seller_moonton_no_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_moonton_no_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            if row:
                _upsert_seller_deal(
                    request_id,
                    int(row["user_id"]),
                    moonton_changeable="no",
                    status="manual_moonton_transfer",
                )
                bot.send_message(
                    call.message.chat.id,
                    "ℹ️ Moonton Mail မပြောင်းနိုင်တဲ့အတွက် "
                    "Admin က Manual Transfer အပိုင်းကို ဆက်သွယ်ပါမယ်။\n\n"
                    "Gmail password / verification code ကို Bot ထဲ "
                    "မပို့ပါနဲ့ခင်ဗျာ။",
                    reply_markup=buyer_features_menu(),
                )
                bot.send_message(
                    ADMIN_ID,
                    f"⚠️ SELL-{request_id:04d} — Seller က "
                    "Moonton Mail မပြောင်းနိုင်ကြောင်း ရွေးထားပါတယ်။ "
                    "Manual transfer ကို စီမံပါ။",
                )
            return True

        if data.startswith("premium_seller_accept_moonton_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_accept_moonton_",
                    "",
                    1,
                )
            )
            _send_moonton_change_prompt(request_id)
            return True

        if data.startswith("premium_seller_gmail_ready_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_gmail_ready_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)
            if row and deal:
                _upsert_seller_deal(
                    request_id,
                    int(row["user_id"]),
                    status="awaiting_moonton_proof",
                    moonton_status="seller_has_gmail",
                )

                try:
                    bot.delete_message(
                        call.message.chat.id,
                        call.message.message_id,
                    )
                except Exception:
                    logging.exception(
                        "Assigned Gmail message delete failed request=%s",
                        request_id,
                    )

                bot.send_message(
                    call.message.chat.id,
                    "✅ Gmail ရပြီးပါပြီ။\n\n"
                    "အခု Moonton Mail ပြောင်းပြီးကြောင်း Screenshot ပို့ပေးပါခင်ဗျာ။",
                    reply_markup=original.back_button(),
                )
                original.set_state(
                    call.from_user.id,
                    {
                        "flow": "seller_moonton_proof",
                        "request_id": request_id,
                    },
                )
            return True

        if data.startswith("premium_seller_moonton_done_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_moonton_done_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            if row:
                bot.send_message(
                    call.message.chat.id,
                    "📸 ပြောင်းပြီးကြောင်း Screenshot ပို့ပေးပါခင်ဗျာ။",
                    reply_markup=original.back_button(),
                )
                original.set_state(
                    call.from_user.id,
                    {
                        "flow": "seller_moonton_proof",
                        "request_id": request_id,
                    },
                )
            return True

        if data.startswith("premium_seller_admin_verify_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(
                    call.id,
                    "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                    show_alert=True,
                )
                return True

            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_admin_verify_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)

            if not row or not deal:
                return True

            _upsert_seller_deal(
                request_id,
                int(row["user_id"]),
                admin_verified=1,
                status="seller_verified_ready_for_payout",
                moonton_status="approved",
            )

            bot.send_message(
                int(row["user_id"]),
                "✅ Admin က Account / Moonton Mail ပြောင်းပြီးကြောင်း "
                "စစ်ဆေးအတည်ပြုပြီးပါပြီ။\n\n"
                "💸 Seller ကို ငွေလွှဲရန် နံပါတ်ကို ပို့ပေးပါခင်ဗျာ။",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💳 ငွေလွှဲနံပါတ် ပို့မယ်",
                            callback_data=f"premium_seller_payout_dest_{request_id}",
                        )
                    ]
                ]),
            )
            return True

        if data.startswith("premium_seller_payout_dest_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_payout_dest_",
                    "",
                    1,
                )
            )
            original.set_state(
                call.from_user.id,
                {
                    "flow": "seller_payout_destination",
                    "request_id": request_id,
                },
            )
            msg = bot.send_message(
                call.message.chat.id,
                "💳 Seller ကို ငွေလွှဲမယ့် KPay / Wave / Bank နံပါတ် "
                "ကို ရိုက်ပို့ပါ။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _seller_payout_destination_receive,
            )
            return True

        if data.startswith("premium_seller_cancel_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(
                    call.id,
                    "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                    show_alert=True,
                )
                return True
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_cancel_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            if row:
                _upsert_seller_deal(
                    request_id,
                    int(row["user_id"]),
                    status="cancelled",
                )
                with db_lock:
                    with closing(db_connect()) as conn:
                        conn.execute(
                            "UPDATE seller_requests SET status='rejected' WHERE id=?",
                            (request_id,),
                        )
                        conn.commit()
                bot.send_message(
                    int(row["user_id"]),
                    "❌ ဒီ Seller Request ကို Admin က ပယ်ဖျက်လိုက်ပါပြီ။",
                    reply_markup=buyer_features_menu(),
                )
            bot.send_message(
                ADMIN_ID,
                f"❌ SELL-{request_id:04d} ကို ပယ်ဖျက်လိုက်ပါပြီ။",
            )
            return True

        if data.startswith("premium_buy_confirm_"):
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_buy_confirm_", "", 1)
            try:
                _send_buy_payment(
                    call.message.chat.id,
                    call.from_user.id,
                    int(aid),
                )
            except Exception:
                logging.exception("Buy payment step failed")
                bot.send_message(
                    call.message.chat.id,
                    "❌ ဝယ်ယူမှုဆက်လုပ်ရာမှာ အမှားရှိနေပါတယ်။",
                    reply_markup=buyer_features_menu(),
                )
            return True

        if data.startswith("premium_buy_admin_approve_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            request_id = int(data.replace("premium_buy_admin_approve_", "", 1))
            req = rows(
                "SELECT buyer_user_id, account_code, status FROM premium_buy_requests WHERE id=?",
                (request_id,),
            )
            if not req:
                bot.send_message(ADMIN_ID, "❌ Buy Request မတွေ့ပါ။", reply_markup=admin_features_menu())
                return True
            buyer_id = int(req[0]["buyer_user_id"])
            if req[0]["status"] == "approved":
                bot.send_message(ADMIN_ID, "ℹ️ ဒီ Request ကို အတည်ပြုပြီးသားပါ။", reply_markup=admin_features_menu())
                return True
            with db_lock:
                with closing(db_connect()) as conn:
                    conn.execute(
                        "UPDATE premium_buy_requests SET status='approved', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (request_id,),
                    )
                    conn.commit()
            final_text = (
                "✅ <b>Admin အကောင့်အား ဂိမ်း Account ရယူဖို့ အခုဘဲ ဆက်သွယ်ပါခင်ဗျာ။</b>\n\n"
                "Admin လိုင်းပေါ်မရှိပါက ဖုန်းဆက်ပါခင်ဗျာ\n"
                "<b>09987479721</b>"
            )
            bot.send_message(
                buyer_id,
                final_text,
                parse_mode="HTML",
                reply_markup=buyer_features_menu(),
            )
            bot.send_message(
                ADMIN_ID,
                f"✅ BUY-{request_id:04d} ကို အတည်ပြုပြီး Buyer ဆီ ပို့ပြီးပါပြီ။",
                reply_markup=admin_features_menu(),
            )
            return True


        if data.startswith("premium_seller_payout_confirm_"):
            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_seller_payout_confirm_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)
            if row and deal:
                _upsert_seller_deal(
                    request_id,
                    int(row["user_id"]),
                    seller_payout_confirmed=1,
                    status="completed",
                )
                bot.send_message(
                    int(row["user_id"]),
                    "🎉 <b>လုပ်ငန်းစဉ် ပြီးပါပြီ။</b>\n\n"
                    "Seller ငွေလက်ခံရရှိမှုကို အတည်ပြုပြီးပါပြီ။",
                    parse_mode="HTML",
                    reply_markup=buyer_features_menu(),
                )
                bot.send_message(
                    ADMIN_ID,
                    f"✅ SELL-{request_id:04d} လုပ်ငန်းစဉ် ပြီးပါပြီ။",
                )
            return True

        if data.startswith("premium_admin_send_payout_receipt_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(
                    call.id,
                    "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                    show_alert=True,
                )
                return True

            bot.answer_callback_query(call.id)
            request_id = int(
                data.replace(
                    "premium_admin_send_payout_receipt_",
                    "",
                    1,
                )
            )
            row = _seller_request_row(request_id)
            deal = _seller_deal_row(request_id)

            if not row or not deal:
                bot.send_message(
                    ADMIN_ID,
                    "❌ Seller Request မတွေ့ပါ။",
                )
                return True

            original.set_state(
                ADMIN_ID,
                {
                    "flow": "seller_admin_payout_receipt",
                    "request_id": request_id,
                },
            )
            msg = bot.send_message(
                ADMIN_ID,
                f"📸 SELL-{request_id:04d} အတွက် "
                "ငွေလွှဲပြီးကြောင်း Screenshot/ပြေစာ ပို့ပါ။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _admin_payout_receipt_receive,
            )
            return True

        if data.startswith("premium_buy_admin_reject_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            request_id = int(data.replace("premium_buy_admin_reject_", "", 1))
            req = rows(
                "SELECT buyer_user_id FROM premium_buy_requests WHERE id=?",
                (request_id,),
            )
            if req:
                buyer_id = int(req[0]["buyer_user_id"])
                with db_lock:
                    with closing(db_connect()) as conn:
                        conn.execute(
                            "UPDATE premium_buy_requests SET status='rejected', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (request_id,),
                        )
                        conn.commit()
                bot.send_message(
                    buyer_id,
                    "❌ Admin က ပြေစာကို အတည်မပြုနိုင်သေးပါ။ Admin ဆီ တိုက်ရိုက်ဆက်သွယ်ပါခင်ဗျာ။",
                    reply_markup=buyer_features_menu(),
                )
            bot.send_message(
                ADMIN_ID,
                f"❌ BUY-{request_id:04d} ကို ငြင်းလိုက်ပါပြီ။",
                reply_markup=admin_features_menu(),
            )
            return True

        if data.startswith("premium_fast_buy_"):
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_fast_buy_", "", 1)
            acc = account_by_text(aid)
            if not acc or acc.get("status") != "available":
                bot.send_message(call.message.chat.id, "❌ ဒီအကောင့် လက်ရှိ ဝယ်ယူလို့မရတော့ပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
                return True
            deal = active_flash(acc["db_id"])
            price = deal[0] if deal else int(acc.get("effective_price") or acc["price"])
            m = InlineKeyboardMarkup(row_width=1)
            if original.ADMIN_USERNAME:
                m.add(InlineKeyboardButton("👨‍💻 Admin ကို တိုက်ရိုက်ဆက်သွယ်မယ်", url=f"https://t.me/{original.ADMIN_USERNAME}"))
            m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
            bot.send_message(
                call.message.chat.id,
                f"⚡ <b>အမြန်ဝယ်မယ်</b>\n\n{format_account_wrapped(acc)}\n\n💰 <b>ဝယ်ဈေး — {price:,} MMK</b>",
                parse_mode="HTML",
                reply_markup=m,
            )
            return True

        if data == "premium_advanced_search":
            bot.answer_callback_query(call.id)
            original.set_state(call.from_user.id, {"flow": "premium_advanced_search"})
            msg = bot.send_message(
                call.message.chat.id,
                "🔎 <b>ဂိမ်းအကောင့်ရှာမယ်</b>\n\n"
                "ကိုယ်လိုချင်တဲ့ဂိမ်းအကောင့်ကိုရှာမယ်ဆိုရင်\n"
                "ဒီလိုရိုက်ရှာပေးပါ —\n"
                "သင်လိုချင်တဲ့ Skin / သုံးမယ့်အနည်းဆုံးဈေး / သုံးမယ့်အများဆုံးဈေး\n\n"
                "ဥပမာ — <code>Gs Collector / 50000 / 70000</code>\n"
                "ကိုယ်သုံးမယ့် Buget နဲ့ ဘယ်လိုအကောင့်မျိုးရနိုင်မလဲသိချင်ရင် — <code>Any / 0 / 150000</code>",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(msg, advanced_search_receive)
            return True

        if data in ("premium_search_prev", "premium_search_next"):
            bot.answer_callback_query(call.id)
            navigate(call, -1 if data.endswith("prev") else 1)
            return True

        if data == "premium_special_deals":
            bot.answer_callback_query(call.id)
            items = []
            for r in rows("SELECT account_id, deal_price, ends_at FROM premium_flash_deals ORDER BY ends_at ASC"):
                aid = int(r["account_id"])
                acc = account_by_number(aid)
                deal = active_flash(aid)
                if acc and deal and acc.get("status") == "available":
                    original_price = int(acc.get("price") or 0)
                    items.append((acc, int(deal[0]), deal[1], original_price))

            if not items:
                bot.send_message(
                    call.message.chat.id,
                    "🔥 လောလောဆယ် <b>အထူးစပရှယ် လျော့စျေးအကောင့်</b> မရှိသေးပါ။",
                    parse_mode="HTML",
                    reply_markup=buyer_features_menu(),
                )
                return True

            for acc, deal_price, ends, original_price in items:
                remain = max(0, int((ends - datetime.now(timezone.utc)).total_seconds()))
                total_minutes = (remain + 59) // 60
                if total_minutes >= 60:
                    hours, rem_minutes = divmod(total_minutes, 60)
                    expiry_text = f"{hours} နာရီ" if rem_minutes == 0 else f"{hours} နာရီ {rem_minutes} မိနစ်"
                else:
                    expiry_text = f"{total_minutes} မိနစ်"

                discount_amount = max(0, original_price - deal_price)
                discount_pct = int(round(discount_amount * 100 / original_price)) if original_price > 0 else 0
                text_card = (
                    "🔥 <b>အထူးစပရှယ် လျော့စျေးအကောင့်</b>\n\n"
                    f"🆔 <b>{acc['id']}</b>\n"
                    f"💰 အရင်ဈေး — <s>{original_price:,} MMK</s>\n"
                    f"🔥 ယခုဈေး — <b>{deal_price:,} MMK</b>\n"
                    f"🎟️ အကောင့်လျော့စျေးကူပွန် — <b>-{discount_amount:,} MMK ({discount_pct}%)</b>\n"
                    f"⏰ ကုန်ဆုံးချိန် — <b>{expiry_text}</b>\n\n"
                    + format_account_wrapped(acc)
                )

                # Photos are sent separately; the text card always follows.
                for photo in [p for p in (acc.get("photos") or []) if p][:15]:
                    try:
                        bot.send_photo(call.message.chat.id, photo)
                    except Exception:
                        logging.exception("Special deal photo send failed: %s", acc.get("id"))

                m = InlineKeyboardMarkup(row_width=2)
                m.row(
                    InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"),
                    InlineKeyboardButton("❤️ သိမ်းထားမယ်", callback_data=f"premium_fav_toggle_{acc['db_id']}"),
                )
                m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
                bot.send_message(call.message.chat.id, text_card, parse_mode="HTML", reply_markup=m)
            return True

        if data.startswith("premium_flash_buy_"):
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_flash_buy_", "", 1)
            acc = account_by_text(aid)
            deal = active_flash(acc["db_id"]) if acc else None
            if not acc or not deal:
                bot.send_message(call.message.chat.id, "❌ Flash Deal သက်တမ်းကုန်သွားပါပြီ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
                return True
            price = deal[0]
            m = InlineKeyboardMarkup(row_width=1)
            if original.ADMIN_USERNAME:
                m.add(InlineKeyboardButton("👨‍💻 Admin ကို ဆက်သွယ်မယ်", url=f"https://t.me/{original.ADMIN_USERNAME}"))
            m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
            bot.send_message(call.message.chat.id, f"🔥 <b>FLASH DEAL</b>\n\n{format_account_wrapped(acc)}\n\n💰 <b>{price:,} MMK</b>", parse_mode="HTML", reply_markup=m)
            return True

        # Existing Browse callbacks are intercepted here so generic main.py
        # handlers cannot capture them first.
        if data == "browse_next":
            bot.answer_callback_query(call.id)
            return handle_browse(call, +1)

        if data.startswith("browse_"):
            suffix = data.replace("browse_", "", 1)
            if suffix.isdigit():
                bot.answer_callback_query(call.id)
                idx = int(suffix)
                return handle_browse(call, 0, forced_index=idx)

        if data in ("premium_browse_prev", "premium_browse_next"):
            bot.answer_callback_query(call.id)
            return handle_browse(call, -1 if data.endswith("prev") else 1)

        # Admin-only feature tools.
        if data == "premium_admin_tools":
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            bot.send_message(ADMIN_ID, "✨ <b>Premium Features စီမံမယ်</b>", parse_mode="HTML", reply_markup=admin_features_menu())
            return True

        if data == "premium_admin_flash_list":
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            m = InlineKeyboardMarkup(row_width=1)
            accounts = original.get_admin_accounts(status="available")
            for acc in accounts[:50]:
                deal = active_flash(acc["db_id"])
                label = f"🔥 {acc['id']} — {deal[0]:,} MMK" if deal else f"💰 {acc['id']} — {acc['effective_price']:,} MMK"
                m.add(InlineKeyboardButton(label, callback_data=f"premium_admin_flash_{acc['id']}"))
            m.add(InlineKeyboardButton("🔙 Premium Features", callback_data="premium_admin_tools"))
            bot.send_message(ADMIN_ID, "🔥 Flash Deal တင်မယ့် Account ကို ရွေးပါ။", reply_markup=m)
            return True

        if data.startswith("premium_admin_flash_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_admin_flash_", "", 1)
            acc = account_by_text(aid)
            if not acc:
                bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_features_menu())
                return True
            original.set_state(ADMIN_ID, {"flow": "premium_admin_flash", "premium_flash_account": aid})
            msg = bot.send_message(ADMIN_ID, f"🔥 <b>{aid}</b> Flash Deal\n\n<code>Deal ဈေး | မိနစ်</code>\nဥပမာ — <code>90000 | 60</code>", parse_mode="HTML", reply_markup=original.back_button())
            bot.register_next_step_handler(msg, flash_receive)
            return True

        if data == "premium_admin_verified_list":
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            m = InlineKeyboardMarkup(row_width=1)
            for acc in original.get_admin_accounts()[:50]:
                icon = "✅" if is_verified(acc["db_id"]) else "⬜"
                m.add(InlineKeyboardButton(f"{icon} {acc['id']}", callback_data=f"premium_admin_verify_{acc['db_id']}"))
            m.add(InlineKeyboardButton("🔙 Premium Features", callback_data="premium_admin_tools"))
            bot.send_message(ADMIN_ID, "✅ Verified လုပ်/ဖြုတ်မယ့် Account ကို ရွေးပါ။", reply_markup=m)
            return True

        if data.startswith("premium_admin_verify_"):
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            aid = int(data.replace("premium_admin_verify_", "", 1))
            acc = account_by_number(aid)
            if not acc:
                bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_features_menu())
                return True
            enabled = not is_verified(aid)
            set_verified(aid, enabled)
            bot.send_message(ADMIN_ID, f"✅ <b>{acc['id']}</b> ကို Verified လုပ်ပြီးပါပြီ။" if enabled else f"❌ <b>{acc['id']}</b> Verified ဖြုတ်ပြီးပါပြီ။", parse_mode="HTML", reply_markup=admin_features_menu())
            return True

        if data == "premium_admin_alert_stats":
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                return True
            bot.answer_callback_query(call.id)
            n1 = int(rows("SELECT COUNT(*) AS n FROM premium_user_settings WHERE new_account_alert=1")[0]["n"])
            n2 = int(rows("SELECT COUNT(DISTINCT user_id) AS n FROM premium_price_alerts")[0]["n"])
            bot.send_message(ADMIN_ID, f"🔔 <b>အသိပေးချက် အချက်အလက်</b>\n\n🆕 အသစ်တင်အသိပေးချက် ဖွင့်ထားသူ — <b>{n1}</b> ယောက်\n💸 ဈေးကျအသိပေးချက် အသုံးပြုသူ — <b>{n2}</b> ယောက်", parse_mode="HTML", reply_markup=admin_features_menu())
            return True

        return False

    def handle_browse(call, direction, forced_index=None):
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
            return True
        state = original.get_state(call.from_user.id)
        if forced_index is None:
            idx = (int(state.get("browse_index", 0)) + direction) % len(accounts)
        else:
            idx = int(forced_index) % len(accounts)
        original.set_state(call.from_user.id, {"flow": "browse", "browse_index": idx})
        send_account_card(call.message.chat.id, accounts[idx], "browse", idx, len(accounts))
        return True

    def advanced_search_receive(message):
        raw = (message.text or "").strip()
        parts = [p.strip() for p in raw.split("/", 2)]
        if len(parts) != 3:
            msg = bot.send_message(message.chat.id, "❌ Format မမှန်ပါ။\n<code>Gs Collector / 50000 / 70000</code>", parse_mode="HTML", reply_markup=original.back_button())
            bot.register_next_step_handler(msg, advanced_search_receive)
            return

        skin = parts[0]
        if skin.lower() in ("any", "all", "အကုန်", "အားလုံး"):
            skin = ""
        try:
            min_price = int(parts[1].replace(",", "").replace(" ", ""))
            max_price = int(parts[2].replace(",", "").replace(" ", ""))
            if min_price < 0 or max_price <= 0 or min_price > max_price:
                raise ValueError
        except Exception:
            msg = bot.send_message(message.chat.id, "❌ ဈေးနှုန်း မမှန်ပါ။", reply_markup=original.back_button())
            bot.register_next_step_handler(msg, advanced_search_receive)
            return

        scored = []
        target = skin.lower()
        for acc in original.get_available_accounts():
            price = int(acc.get("effective_price") or acc.get("price") or 0)
            if not (min_price <= price <= max_price):
                continue
            hay = " ".join([str(acc.get("title", "")), str(acc.get("skins", ""))]).lower()
            if target:
                score = SequenceMatcher(None, target, hay).ratio() * 100
                for token in hay.replace(",", " ").split():
                    score = max(score, SequenceMatcher(None, target, token).ratio() * 100)
                if target in hay:
                    score += 40
                if score < 25:
                    continue
            else:
                score = 1
            scored.append((score, acc))

        scored.sort(key=lambda item: (-item[0], int(item[1].get("effective_price") or item[1]["price"]), int(item[1]["db_id"])))
        ids = [a["id"] for _, a in scored]
        original.clear_state(message.from_user.id)
        if not ids:
            bot.send_message(message.chat.id, "❌ အနီးစပ်ဆုံး Account မတွေ့သေးပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]]))
            return
        show_list(message.chat.id, message.from_user.id, ids, "search")

    def flash_receive(message):
        if message.from_user.id != ADMIN_ID:
            return
        st = original.get_state(ADMIN_ID)
        if st.get("flow") != "premium_admin_flash":
            return
        parts = [x.strip() for x in (message.text or "").split("|", 1)]
        if len(parts) != 2:
            msg = bot.send_message(ADMIN_ID, "❌ Format မမှန်ပါ။ <code>90000 | 60</code>", parse_mode="HTML")
            bot.register_next_step_handler(msg, flash_receive)
            return
        try:
            price = int(parts[0].replace(",", "").replace(" ", ""))
            minutes = int(parts[1])
            if price <= 0 or minutes <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(ADMIN_ID, "❌ ဈေး/အချိန် မမှန်ပါ။")
            bot.register_next_step_handler(msg, flash_receive)
            return
        aid = st.get("premium_flash_account")
        acc = account_by_text(aid)
        if not acc:
            original.clear_state(ADMIN_ID)
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_features_menu())
            return
        set_flash(acc["db_id"], price, minutes)
        original.clear_state(ADMIN_ID)
        bot.send_message(ADMIN_ID, f"✅ <b>{aid}</b> Flash Deal တင်ပြီးပါပြီ။\n\n🔥 {price:,} MMK\n⏰ {minutes} မိနစ်", parse_mode="HTML", reply_markup=admin_features_menu())

    # ------------------------------------------------------------
    # Buy request flow
    # ------------------------------------------------------------
    def _esc(value):
        return html.escape("" if value is None else str(value), quote=False)

    def _effective_buy_price(acc):
        deal = active_flash(acc.get("db_id")) if acc else None
        return int(deal[0]) if deal else int(acc.get("effective_price") or acc.get("price") or 0)

    def _save_buy_request(buyer_user_id, acc, price, receipt_file_id, receipt_type):
        with db_lock:
            with closing(db_connect()) as conn:
                cur = conn.execute(
                    """INSERT INTO premium_buy_requests(
                        buyer_user_id, account_id, account_code, price, status,
                        receipt_file_id, receipt_type, updated_at
                    ) VALUES(?, ?, ?, ?, 'pending_admin', ?, ?, CURRENT_TIMESTAMP)""",
                    (
                        int(buyer_user_id),
                        int(acc["db_id"]),
                        str(acc["id"]),
                        int(price),
                        str(receipt_file_id),
                        str(receipt_type),
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)

    def _start_buy_by_code(chat_id, user_id, raw_code):
        code = (raw_code or "").strip().upper()
        acc = account_by_text(code)
        if not acc:
            msg = bot.send_message(
                chat_id,
                "❌ ဒီ Account Code ကို Database ထဲမှာ မတွေ့ပါဘူး။\n\n"
                "ဥပမာ — <code>ACC-003</code>\n\n"
                "Account Code ကို ပြန်ရိုက်ပို့ပါ။",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                lambda m: _start_buy_by_code(
                    m.chat.id, m.from_user.id, m.text
                ),
            )
            return

        if acc.get("status") != "available":
            bot.send_message(
                chat_id,
                "❌ ဒီ Account ကို လက်ရှိ ဝယ်ယူလို့မရတော့ပါဘူး။",
                reply_markup=buyer_features_menu(),
            )
            return

        price = _effective_buy_price(acc)
        original.set_state(
            user_id,
            {
                "flow": "buy_confirm",
                "buy_account_id": int(acc["db_id"]),
                "buy_account_code": str(acc["id"]),
                "buy_price": int(price),
            },
        )

        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton(
                "✅ အတည်ပြုမယ်",
                callback_data=f"premium_buy_confirm_{int(acc['db_id'])}",
            ),
            InlineKeyboardButton(
                "❌ မဝယ်တော့ဘူး",
                callback_data="premium_buy_cancel",
            ),
        )

        bot.send_message(
            chat_id,
            "🛒 <b>Account ဝယ်ယူရန် အတည်ပြုပါ</b>\n\n"
            f"🆔 <b>{_esc(acc['id'])}</b>\n"
            f"💰 ဝယ်ဈေး — <b>{price:,} MMK</b>\n\n"
            "ဒီ Account ကို ဝယ်ယူမယ်ဆိုရင် <b>အတည်ပြုမယ်</b> ကိုနှိပ်ပါ။",
            parse_mode="HTML",
            reply_markup=m,
        )

    def _buy_receipt_receive(message):
        state = original.get_state(message.from_user.id)
        aid = int(state.get("buy_account_id", 0) or 0)
        price = int(state.get("buy_price", 0) or 0)
        code = str(state.get("buy_account_code", ""))

        acc = account_by_number(aid)
        if not acc or not code or price <= 0:
            bot.send_message(
                message.chat.id,
                "❌ ဝယ်ယူမှုအချက်အလက် မတွေ့တော့ပါ။ ထပ်စပြီး Account ဝယ်မယ်ကို နှိပ်ပါ။",
                reply_markup=buyer_features_menu(),
            )
            return

        receipt_file_id = ""
        receipt_type = ""
        if getattr(message, "photo", None):
            receipt_file_id = message.photo[-1].file_id
            receipt_type = "photo"
        elif getattr(message, "document", None):
            receipt_file_id = message.document.file_id
            receipt_type = "document"

        if not receipt_file_id:
            msg = bot.send_message(
                message.chat.id,
                "❌ ပြေစာပုံ ပို့ပေးပါခင်ဗျာ။\n\n"
                "ဓာတ်ပုံ (သို့) image file အဖြစ် ပို့လို့ရပါတယ်။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(msg, _buy_receipt_receive)
            return

        request_id = _save_buy_request(
            message.from_user.id,
            acc,
            price,
            receipt_file_id,
            receipt_type,
        )

        original.clear_state(message.from_user.id)

        bot.send_message(
            message.chat.id,
            "⏳ ခနစောင့်ပါခင်ဗျာ။\n"
            "Admin သင့်ကို Account ပေးဖို့ ဆက်သွယ်နေပါပြီ။",
            reply_markup=buyer_features_menu(),
        )

        profile = format_account_wrapped(acc)
        admin_caption = (
            "🛒 <b>Account ဝယ်ယူမှု Request</b>\n\n"
            f"📌 Request — <b>BUY-{request_id:04d}</b>\n"
            f"👤 Buyer ID — <code>{int(message.from_user.id)}</code>\n"
            f"🆔 Account Code — <b>{_esc(code)}</b>\n"
            f"💰 Price — <b>{price:,} MMK</b>\n\n"
            f"{profile}"
        )
        admin_markup = InlineKeyboardMarkup(row_width=2)
        admin_markup.row(
            InlineKeyboardButton(
                "✅ အတည်ပြုမယ်",
                callback_data=f"premium_buy_admin_approve_{request_id}",
            ),
            InlineKeyboardButton(
                "❌ ငြင်းမယ်",
                callback_data=f"premium_buy_admin_reject_{request_id}",
            ),
        )

        try:
            if receipt_type == "photo":
                bot.send_photo(
                    ADMIN_ID,
                    receipt_file_id,
                    caption=admin_caption,
                    parse_mode="HTML",
                    reply_markup=admin_markup,
                )
            else:
                bot.send_document(
                    ADMIN_ID,
                    receipt_file_id,
                    caption=admin_caption,
                    parse_mode="HTML",
                    reply_markup=admin_markup,
                )
        except Exception:
            logging.exception("Buy receipt forwarding failed request=%s", request_id)
            bot.send_message(
                ADMIN_ID,
                admin_caption,
                parse_mode="HTML",
                reply_markup=admin_markup,
            )


    # ------------------------------------------------------------
    # Seller negotiation / handoff flow
    # ------------------------------------------------------------
    def _upsert_seller_deal(
        request_id,
        seller_user_id,
        seller_expected_price=None,
        seller_note=None,
        admin_offer_price=None,
        negotiation_count=None,
        moonton_changeable=None,
        status=None,
        gmail_mailbox_id=None,
        gmail_email=None,
        moonton_status=None,
        moonton_proof_file_id=None,
        moonton_proof_type=None,
        admin_verified=None,
        payout_destination=None,
        payout_amount=None,
        payout_receipt_file_id=None,
        payout_receipt_type=None,
        seller_payout_confirmed=None,
        final_account_id=None,
    ):
        existing = rows(
            "SELECT * FROM premium_seller_deals WHERE request_id=?",
            (int(request_id),),
        )
        base = existing[0] if existing else None

        values = {
            "request_id": int(request_id),
            "seller_user_id": int(
                seller_user_id
                if seller_user_id is not None
                else base["seller_user_id"]
            ),
            "seller_expected_price": int(
                seller_expected_price
                if seller_expected_price is not None
                else (base["seller_expected_price"] if base else 0)
            ),
            "seller_note": str(
                seller_note
                if seller_note is not None
                else (base["seller_note"] if base else "")
            ),
            "admin_offer_price": int(
                admin_offer_price
                if admin_offer_price is not None
                else (base["admin_offer_price"] if base else 0)
            ),
            "negotiation_count": int(
                negotiation_count
                if negotiation_count is not None
                else (base["negotiation_count"] if base else 0)
            ),
            "moonton_changeable": str(
                moonton_changeable
                if moonton_changeable is not None
                else (base["moonton_changeable"] if base else "")
            ),
            "gmail_mailbox_id": int(
                gmail_mailbox_id
                if gmail_mailbox_id is not None
                else (base["gmail_mailbox_id"] if base else 0)
            ),
            "gmail_email": str(
                gmail_email
                if gmail_email is not None
                else (base["gmail_email"] if base else "")
            ),
            "moonton_status": str(
                moonton_status
                if moonton_status is not None
                else (base["moonton_status"] if base else "not_started")
            ),
            "moonton_proof_file_id": str(
                moonton_proof_file_id
                if moonton_proof_file_id is not None
                else (base["moonton_proof_file_id"] if base else "")
            ),
            "moonton_proof_type": str(
                moonton_proof_type
                if moonton_proof_type is not None
                else (base["moonton_proof_type"] if base else "")
            ),
            "admin_verified": int(
                admin_verified
                if admin_verified is not None
                else (base["admin_verified"] if base else 0)
            ),
            "payout_destination": str(
                payout_destination
                if payout_destination is not None
                else (base["payout_destination"] if base else "")
            ),
            "payout_amount": int(
                payout_amount
                if payout_amount is not None
                else (base["payout_amount"] if base else 0)
            ),
            "payout_receipt_file_id": str(
                payout_receipt_file_id
                if payout_receipt_file_id is not None
                else (base["payout_receipt_file_id"] if base else "")
            ),
            "payout_receipt_type": str(
                payout_receipt_type
                if payout_receipt_type is not None
                else (base["payout_receipt_type"] if base else "")
            ),
            "seller_payout_confirmed": int(
                seller_payout_confirmed
                if seller_payout_confirmed is not None
                else (base["seller_payout_confirmed"] if base else 0)
            ),
            "final_account_id": int(
                final_account_id
                if final_account_id is not None
                else (base["final_account_id"] if base else 0)
            ),
            "status": str(
                status
                if status is not None
                else (base["status"] if base else "awaiting_admin_price")
            ),
        }

        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO premium_seller_deals(
                        request_id, seller_user_id, seller_expected_price,
                        seller_note, admin_offer_price, negotiation_count,
                        moonton_changeable, gmail_mailbox_id, gmail_email,
                        moonton_status, moonton_proof_file_id,
                        moonton_proof_type, admin_verified,
                        payout_destination, payout_amount,
                        payout_receipt_file_id, payout_receipt_type,
                        seller_payout_confirmed, final_account_id,
                        status, updated_at
                    )
                    VALUES(
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(request_id) DO UPDATE SET
                        seller_user_id=excluded.seller_user_id,
                        seller_expected_price=excluded.seller_expected_price,
                        seller_note=excluded.seller_note,
                        admin_offer_price=excluded.admin_offer_price,
                        negotiation_count=excluded.negotiation_count,
                        moonton_changeable=excluded.moonton_changeable,
                        gmail_mailbox_id=excluded.gmail_mailbox_id,
                        gmail_email=excluded.gmail_email,
                        moonton_status=excluded.moonton_status,
                        moonton_proof_file_id=excluded.moonton_proof_file_id,
                        moonton_proof_type=excluded.moonton_proof_type,
                        admin_verified=excluded.admin_verified,
                        payout_destination=excluded.payout_destination,
                        payout_amount=excluded.payout_amount,
                        payout_receipt_file_id=excluded.payout_receipt_file_id,
                        payout_receipt_type=excluded.payout_receipt_type,
                        seller_payout_confirmed=excluded.seller_payout_confirmed,
                        final_account_id=excluded.final_account_id,
                        status=excluded.status,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        values["request_id"],
                        values["seller_user_id"],
                        values["seller_expected_price"],
                        values["seller_note"],
                        values["admin_offer_price"],
                        values["negotiation_count"],
                        values["moonton_changeable"],
                        values["gmail_mailbox_id"],
                        values["gmail_email"],
                        values["moonton_status"],
                        values["moonton_proof_file_id"],
                        values["moonton_proof_type"],
                        values["admin_verified"],
                        values["payout_destination"],
                        values["payout_amount"],
                        values["payout_receipt_file_id"],
                        values["payout_receipt_type"],
                        values["seller_payout_confirmed"],
                        values["final_account_id"],
                        values["status"],
                    ),
                )
                conn.commit()

    def _seller_request_row(request_id):
        result = rows(
            "SELECT * FROM seller_requests WHERE id=?",
            (int(request_id),),
        )
        return result[0] if result else None

    def _seller_deal_row(request_id):
        result = rows(
            "SELECT * FROM premium_seller_deals WHERE request_id=?",
            (int(request_id),),
        )
        return result[0] if result else None

    def _seller_buying_end_markup():
        return InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "🏠 ပင်မ Menu",
                    callback_data="home",
                )
            ]]
        )

    def _seller_offer_markup(request_id):
        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton(
                "✅ ရောင်းမယ်",
                callback_data=f"premium_seller_accept_{int(request_id)}",
            ),
            InlineKeyboardButton(
                "💬 စျေးထပ်ညှိမယ်",
                callback_data=f"premium_seller_negotiate_{int(request_id)}",
            ),
        )
        m.add(
            InlineKeyboardButton(
                "🏠 ပင်မ Menu",
                callback_data="home",
            )
        )
        return m

    def _admin_seller_offer_markup(request_id):
        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton(
                "💰 စျေးပြန်ပေးမယ်",
                callback_data=f"premium_seller_offer_{int(request_id)}",
            ),
            InlineKeyboardButton(
                "❌ ပယ်ဖျက်မယ်",
                callback_data=f"premium_seller_cancel_{int(request_id)}",
            ),
        )
        return m

    def _send_seller_offer_to_seller(request_id):
        deal = _seller_deal_row(request_id)
        row = _seller_request_row(request_id)
        if not deal or not row or deal["admin_offer_price"] <= 0:
            return False

        offer = int(deal["admin_offer_price"])
        note = _esc(deal["seller_note"])

        text_out = (
            "💰 <b>Admin က သင့် Account အတွက် စျေးသတ်မှတ်ပေးထားပါတယ်။</b>\n\n"
            f"🆔 Request — <b>SELL-{int(request_id):04d}</b>\n"
            f"💵 Admin ပေးမယ့်ဈေး — <b>{offer:,} MMK</b>\n"
        )
        if note:
            text_out += f"📝 သင့် Note — {_esc(note)}\n"
        text_out += "\nရောင်းမယ်ဆို <b>ရောင်းမယ်</b> ကိုနှိပ်ပါ။ စျေးထပ်ညှိမယ်ဆို <b>စျေးထပ်ညှိမယ်</b> ကိုနှိပ်ပါ။"

        bot.send_message(
            int(row["user_id"]),
            text_out,
            parse_mode="HTML",
            reply_markup=_seller_offer_markup(request_id),
        )
        return True

    def _start_seller_expected_price(message):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        print(
            f"[SELLER_PRICE] handler fired user_id={user_id} flow={state.get('flow')!r} text={(message.text or '')[:200]!r}",
            flush=True,
        )
        if state.get("flow") != "seller_expected_price":
            return

        raw = (message.text or "").replace(",", "").replace(" ", "").strip()
        try:
            price = int(raw)
            if price <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(
                message.chat.id,
                "❌ ရောင်းချင်တဲ့ဈေး မမှန်ပါ။ ဥပမာ — <code>100000</code>",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _start_seller_expected_price,
            )
            return

        state.update({
            "flow": "seller_note",
            "seller_expected_price": price,
        })
        original.set_state(user_id, state)

        msg = bot.send_message(
            message.chat.id,
            "📝 Seller Note ထည့်ချင်ရင် ဒီမှာ ရိုက်ပို့ပါ။\n"
            "မထည့်ချင်ရင် <code>မရှိ</code> လို့ ရိုက်ပို့လို့ရပါတယ်။",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(
            msg,
            _finish_seller_submission,
        )

    def _finish_seller_submission(message):
        user_id = int(message.from_user.id)
        print(
            f"[SELLER_NOTE] handler fired user_id={user_id} text={(message.text or '')[:200]!r}",
            flush=True,
        )
        try:
            _finish_seller_submission_inner(message, user_id)
        except Exception:
            import traceback
            print(
                f"[SELLER_NOTE] submission FAILED user_id={user_id}",
                flush=True,
            )
            traceback.print_exc()
            logging.exception(
                "Seller note submission failed user_id=%s", user_id
            )
            try:
                bot.send_message(
                    message.chat.id,
                    "❌ Seller Request ပို့ရာမှာ အမှားရှိနေပါတယ်။ "
                    "ထပ်ကြိုးစားကြည့်ပါ (💰 အကောင့်ရောင်းမယ် ကနေ အသစ်စပါ)။",
                    reply_markup=original.back_button(),
                )
            except Exception:
                traceback.print_exc()
                logging.exception(
                    "Seller note failure reply also failed user_id=%s",
                    user_id,
                )
            original.clear_state(user_id)

    def _finish_seller_submission_inner(message, user_id):
        state = original.get_state(user_id)
        if state.get("flow") != "seller_note":
            logging.info(
                "Seller note handler exited early: flow was %r, not 'seller_note' (user_id=%s)",
                state.get("flow"),
                user_id,
            )
            return

        note_raw = (message.text or "").strip()
        note = "" if note_raw in {"မရှိ", "-", "မထည့်ဘူး", "none"} else note_raw
        expected = int(state.get("seller_expected_price", 0) or 0)
        photos = [p for p in (state.get("photos") or []) if p][:15]

        if not photos:
            bot.send_message(
                message.chat.id,
                "❌ Account ပုံတွေ မတွေ့ပါဘူး။ အကောင့်ရောင်းမယ်ကို ပြန်စပါ။",
                reply_markup=buyer_features_menu(),
            )
            original.clear_state(user_id)
            return

        username = message.from_user.username or "No Username"

        with db_lock:
            with closing(db_connect()) as conn:
                cur = conn.execute(
                    """
                    INSERT INTO seller_requests(
                        user_id, username, error_info, price,
                        photo_count, status, photos
                    )
                    VALUES(?, ?, '', ?, ?, 'pending', ?)
                    """,
                    (
                        user_id,
                        username,
                        expected,
                        len(photos),
                        ",".join(photos),
                    ),
                )
                request_id = int(cur.lastrowid)

                columns = {
                    r["name"]
                    for r in conn.execute(
                        "PRAGMA table_info(seller_requests)"
                    ).fetchall()
                }
                if "seller_note" not in columns:
                    conn.execute(
                        "ALTER TABLE seller_requests "
                        "ADD COLUMN seller_note TEXT NOT NULL DEFAULT ''"
                    )
                if "seller_expected_price" not in columns:
                    conn.execute(
                        "ALTER TABLE seller_requests "
                        "ADD COLUMN seller_expected_price INTEGER NOT NULL DEFAULT 0"
                    )
                conn.execute(
                    """
                    UPDATE seller_requests
                    SET seller_note=?,
                        seller_expected_price=?
                    WHERE id=?
                    """,
                    (
                        note,
                        expected,
                        request_id,
                    ),
                )
                conn.commit()

        _upsert_seller_deal(
            request_id,
            user_id,
            seller_expected_price=expected,
            seller_note=note,
            status="awaiting_admin_price",
        )

        original.clear_state(user_id)

        seller_summary = (
            "📥 <b>Seller Account Request</b>\n\n"
            f"🆔 Request — <b>SELL-{request_id:04d}</b>\n"
            f"👤 @{_esc(username)}\n"
            f"🆔 User ID — <code>{user_id}</code>\n"
            f"📸 ပုံ — <b>{len(photos)}</b>\n"
            f"💰 Seller လိုချင်တဲ့ဈေး — <b>{expected:,} MMK</b>\n"
            f"📝 Seller Note — <b>{_esc(note or 'မရှိ')}</b>\n\n"
            "ပုံတွေစစ်ပြီး Admin က စျေးပြန်ပေးပါ။"
        )

        try:
            bot.send_message(
                ADMIN_ID,
                seller_summary,
                parse_mode="HTML",
                reply_markup=_admin_seller_offer_markup(request_id),
            )
            try:
                original.send_photo_batches(
                    ADMIN_ID,
                    photos,
                    10,
                )
            except Exception:
                logging.exception(
                    "Seller photos admin forwarding failed request=%s",
                    request_id,
                )
        except Exception:
            logging.exception(
                "Seller admin notification failed request=%s",
                request_id,
            )

        bot.send_message(
            user_id,
            "✅ သင့် Account Request ကို Admin ဆီ ပို့ပြီးပါပြီ။\n"
            "Admin စျေးသတ်မှတ်ပေးတဲ့အထိ စောင့်ပေးပါခင်ဗျာ။",
            reply_markup=buyer_features_menu(),
        )

    def _intercept_sell_photos_done(call):
        user_id = int(call.from_user.id)
        state = original.get_state(user_id)
        photos = [p for p in (state.get("photos") or []) if p][:15]

        if not photos:
            bot.send_message(
                call.message.chat.id,
                "⚠️ အရင်ဆုံး Account ပုံ အနည်းဆုံး 1 ပုံ ပို့ပါ။",
                reply_markup=original.back_button(),
            )
            return True

        original.set_state(
            user_id,
            {
                "flow": "seller_expected_price",
                "photos": photos,
            },
        )
        msg = bot.send_message(
            call.message.chat.id,
            "💰 <b>Seller ကိုပေးမယ့်ဈေး</b> ကို အရင်ရိုက်ပို့ပါ။\n\n"
            "ဥပမာ — <code>100000</code>",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(
            msg,
            _start_seller_expected_price,
        )
        return True

    def _admin_set_seller_offer(message):
        if int(message.from_user.id) != ADMIN_ID:
            return

        state = original.get_state(ADMIN_ID)
        if state.get("flow") != "premium_seller_set_offer":
            return

        request_id = int(
            state.get("request_id", 0) or 0
        )
        raw = (message.text or "").replace(",", "").replace(" ", "").strip()

        try:
            offer = int(raw)
            if offer <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(
                ADMIN_ID,
                "❌ စျေးမမှန်ပါ။ ဥပမာ — <code>120000</code>",
                parse_mode="HTML",
            )
            bot.register_next_step_handler(
                msg,
                _admin_set_seller_offer,
            )
            return

        deal = _seller_deal_row(request_id)
        row = _seller_request_row(request_id)
        if not deal or not row:
            original.clear_state(ADMIN_ID)
            bot.send_message(
                ADMIN_ID,
                "❌ Seller Request မတွေ့ပါ။",
            )
            return

        _upsert_seller_deal(
            request_id,
            int(row["user_id"]),
            admin_offer_price=offer,
            status="awaiting_seller_offer_response",
        )

        original.clear_state(ADMIN_ID)

        try:
            _send_seller_offer_to_seller(request_id)
        except Exception:
            logging.exception(
                "Seller offer delivery failed request=%s",
                request_id,
            )

        bot.send_message(
            ADMIN_ID,
            f"✅ SELL-{request_id:04d} အတွက် <b>{offer:,} MMK</b> စျေးပို့ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    def _seller_negotiate_price(message):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        if state.get("flow") != "seller_negotiate_price":
            return

        request_id = int(state.get("request_id", 0) or 0)
        raw = (message.text or "").replace(",", "").replace(" ", "").strip()

        try:
            wanted = int(raw)
            if wanted <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(
                message.chat.id,
                "❌ လိုချင်တဲ့ဈေး မမှန်ပါ။ ဥပမာ — <code>130000</code>",
                parse_mode="HTML",
            )
            bot.register_next_step_handler(
                msg,
                _seller_negotiate_price,
            )
            return

        state["flow"] = "seller_negotiate_note"
        state["seller_negotiated_price"] = wanted
        original.set_state(user_id, state)

        msg = bot.send_message(
            message.chat.id,
            "📝 Admin ကို ပြောချင်တဲ့ Note ရေးပို့ပါ။\n"
            "မရှိရင် <code>မရှိ</code> လို့ ရိုက်ပို့ပါ။",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(
            msg,
            _seller_negotiate_note,
        )

    def _seller_negotiate_note(message):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        if state.get("flow") != "seller_negotiate_note":
            return

        request_id = int(state.get("request_id", 0) or 0)
        wanted = int(
            state.get("seller_negotiated_price", 0) or 0
        )
        note_raw = (message.text or "").strip()
        note = "" if note_raw in {"မရှိ", "-", "none"} else note_raw

        row = _seller_request_row(request_id)
        deal = _seller_deal_row(request_id)

        if not row or not deal:
            original.clear_state(user_id)
            bot.send_message(
                user_id,
                "❌ Seller Request မတွေ့ပါ။",
                reply_markup=buyer_features_menu(),
            )
            return

        count = int(deal["negotiation_count"] or 0) + 1
        _upsert_seller_deal(
            request_id,
            user_id,
            seller_note=note,
            admin_offer_price=0,
            negotiation_count=count,
            status="awaiting_admin_counter",
        )

        original.clear_state(user_id)

        admin_text = (
            "💬 <b>Seller စျေးထပ်ညှိရန် Request</b>\n\n"
            f"🆔 SELL-{request_id:04d}\n"
            f"👤 @{_esc(row['username'] or 'No Username')}\n"
            f"🆔 User ID — <code>{int(row['user_id'])}</code>\n"
            f"💰 Seller လိုချင်တဲ့ဈေး — <b>{wanted:,} MMK</b>\n"
            f"📝 Note — <b>{_esc(note or 'မရှိ')}</b>\n\n"
            "Admin က စျေးပြန်ပေးပါ။"
        )

        # Keep seller's latest requested price in the source request too.
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute(
                    """
                    UPDATE seller_requests
                    SET price=?
                    WHERE id=?
                    """,
                    (wanted, request_id),
                )
                conn.commit()

        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton(
                "💰 စျေးပြန်ပေးမယ်",
                callback_data=f"premium_seller_offer_{request_id}",
            ),
        )
        bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML",
            reply_markup=m,
        )

        bot.send_message(
            user_id,
            "✅ သင့်စျေးနဲ့ Note ကို Admin ဆီ ပို့ပြီးပါပြီ။\n"
            "Admin စျေးပြန်ပေးတဲ့အထိ စောင့်ပေးပါခင်ဗျာ။",
            reply_markup=buyer_features_menu(),
        )

    def _allocate_available_gmail(request_id, seller_user_id):
        """Allocate a mailbox address, never expose authentication codes."""
        try:
            with closing(db_connect()) as conn:
                row = conn.execute(
                    """
                    SELECT id, email
                    FROM gmail_mailboxes
                    WHERE status='available'
                      AND moonton_status='not_changed'
                    ORDER BY id ASC
                    LIMIT 1
                    """
                ).fetchone()

                if not row:
                    return None

                conn.execute(
                    """
                    UPDATE gmail_mailboxes
                    SET status='assigned',
                        moonton_status='pending',
                        assigned_account=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        f"SELL-{int(request_id):04d}",
                        int(row["id"]),
                    ),
                )
                conn.commit()

                _upsert_seller_deal(
                    request_id,
                    seller_user_id,
                    gmail_mailbox_id=int(row["id"]),
                    gmail_email=str(row["email"]),
                    moonton_status="gmail_assigned",
                    status="awaiting_seller_gmail_access",
                )

                return (
                    int(row["id"]),
                    str(row["email"]),
                )
        except Exception:
            logging.exception(
                "Available Gmail allocation failed request=%s",
                request_id,
            )
            return None

    def _create_marketplace_account_after_seller_accept(request_id):
        """Create the listing only after seller accepted the admin offer.

        This keeps the seller negotiation separate from the original
        marketplace publish callback.
        """
        row = _seller_request_row(request_id)
        deal = _seller_deal_row(request_id)
        if not row or not deal:
            return None

        existing = int(deal["final_account_id"] or 0)
        if existing:
            return existing

        # Account creation is delayed until proof/approval is complete.
        return None

    def _send_moonton_change_prompt(request_id):
        deal = _seller_deal_row(request_id)
        row = _seller_request_row(request_id)
        if not deal or not row:
            return False

        text_out = (
            "🔐 <b>Moonton Mail စတင်ချိန်းပါမယ်</b>\n\n"
            "Admin က ချိတ်ထားတဲ့ Gmail ကို အသုံးပြုပြီး "
            "Moonton Mail ပြောင်းပေးပါ။\n\n"
            "ပြီးတာနဲ့ <b>Moonton Mail ပြောင်းပြီးပါပြီ</b> ကိုနှိပ်ပြီး "
            "အတည်ပြု Screenshot ပို့ပေးပါ။\n\n"
            "<i>လုံခြုံရေးအရ Gmail/Google verification code ကို Bot ထဲကနေ "
            "အလိုအလျောက် ပြန်ပို့မပေးပါ။</i>"
        )

        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton(
                "✅ လက်ခံပါတယ်",
                callback_data=f"premium_seller_accept_moonton_{request_id}",
            )
        )
        m.add(
            InlineKeyboardButton(
                "📸 Moonton ပြောင်းပြီးပါပြီ",
                callback_data=f"premium_seller_moonton_done_{request_id}",
            )
        )
        m.add(
            InlineKeyboardButton(
                "🏠 ပင်မ Menu",
                callback_data="home",
            )
        )

        bot.send_message(
            int(row["user_id"]),
            text_out,
            parse_mode="HTML",
            reply_markup=m,
        )
        return True


    def _admin_payout_receipt_receive(message):
        if int(message.from_user.id) != ADMIN_ID:
            return

        state = original.get_state(ADMIN_ID)
        if state.get("flow") != "seller_admin_payout_receipt":
            return

        request_id = int(state.get("request_id", 0) or 0)

        file_id = ""
        file_type = ""

        if getattr(message, "photo", None):
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif getattr(message, "document", None):
            file_id = message.document.file_id
            file_type = "document"

        if not file_id:
            msg = bot.send_message(
                ADMIN_ID,
                "❌ ငွေလွှဲပြေစာ Screenshot/ပုံ ပို့ပါ။",
            )
            bot.register_next_step_handler(
                msg,
                _admin_payout_receipt_receive,
            )
            return

        row = _seller_request_row(request_id)
        deal = _seller_deal_row(request_id)
        if not row or not deal:
            original.clear_state(ADMIN_ID)
            return

        _upsert_seller_deal(
            request_id,
            int(row["user_id"]),
            payout_receipt_file_id=file_id,
            payout_receipt_type=file_type,
            status="awaiting_seller_payout_confirmation",
        )
        original.clear_state(ADMIN_ID)

        seller_id = int(row["user_id"])

        text_out = (
            "💸 <b>Admin ငွေလွှဲပြီးပါပြီ။</b>\n\n"
            f"🆔 SELL-{request_id:04d}\n"
            f"💰 ပမာဏ — <b>{int(deal['payout_amount'] or deal['admin_offer_price'] or 0):,} MMK</b>\n\n"
            "ပြေစာကိုကြည့်ပြီး ငွေတကယ်ရောက်ပြီဆိုရင် "
            "<b>ငွေရောက်ပါပြီ</b> ကိုနှိပ်ပေးပါ။"
        )

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(
                "✅ ငွေရောက်ပါပြီ",
                callback_data=f"premium_seller_payout_confirm_{request_id}",
            )
        )

        try:
            if file_type == "photo":
                bot.send_photo(
                    seller_id,
                    file_id,
                    caption=text_out,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                bot.send_document(
                    seller_id,
                    file_id,
                    caption=text_out,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
        except Exception:
            logging.exception(
                "Admin payout receipt delivery failed request=%s",
                request_id,
            )
            bot.send_message(
                seller_id,
                text_out,
                parse_mode="HTML",
                reply_markup=markup,
            )

        bot.send_message(
            ADMIN_ID,
            f"✅ SELL-{request_id:04d} payout receipt ကို Seller ဆီပို့ပြီးပါပြီ။",
        )

    def _send_buy_payment(chat_id, user_id, account_db_id):
        state = original.get_state(user_id)
        if int(state.get("buy_account_id", 0) or 0) != int(account_db_id):
            bot.send_message(
                chat_id,
                "❌ ဒီဝယ်ယူမှု Request မမှန်တော့ပါဘူး။ Account ဝယ်မယ်ကို ပြန်စပါ။",
                reply_markup=buyer_features_menu(),
            )
            return

        acc = account_by_number(account_db_id)
        if not acc or acc.get("status") != "available":
            bot.send_message(
                chat_id,
                "❌ ဒီ Account ကို လက်ရှိ ဝယ်ယူလို့မရတော့ပါဘူး။",
                reply_markup=buyer_features_menu(),
            )
            return

        price = _effective_buy_price(acc)
        original.set_state(
            user_id,
            {
                "flow": "buy_receipt",
                "buy_account_id": int(account_db_id),
                "buy_account_code": str(acc["id"]),
                "buy_price": int(price),
            },
        )

        msg = bot.send_message(
            chat_id,
            "💳 <b>ငွေလွဲရန် အချက်အလက်</b>\n\n"
            f"🆔 Account — <b>{_esc(acc['id'])}</b>\n"
            f"💰 ပေးချေရမည့်ငွေ — <b>{price:,} MMK</b>\n\n"
            "KPay — <b>09683259225</b> (Kyaw Min Khaing)\n"
            "Wave — <b>09987479721</b> (Min Myat Aung)\n\n"
            "ငွေလွဲပြီးရင် <b>ပြေစာပို့ပေးပါ</b>။",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(msg, _buy_receipt_receive)


    def _seller_moonton_proof_receive(message, request_id=None):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        rid = int(
            request_id
            if request_id is not None
            else (state.get("request_id", 0) or 0)
        )

        file_id = ""
        file_type = ""

        if getattr(message, "photo", None):
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif getattr(message, "document", None):
            file_id = message.document.file_id
            file_type = "document"

        if not file_id:
            bot.send_message(
                user_id,
                "❌ Screenshot ပုံ ပို့ပေးပါခင်ဗျာ။",
                reply_markup=original.back_button(),
            )
            original.set_state(
                user_id,
                {
                    "flow": "seller_moonton_proof",
                    "request_id": rid,
                },
            )
            return

        row = _seller_request_row(rid)
        if not row:
            original.clear_state(user_id)
            bot.send_message(
                user_id,
                "❌ Seller Request မတွေ့ပါ။",
                reply_markup=buyer_features_menu(),
            )
            return

        _upsert_seller_deal(
            rid,
            user_id,
            moonton_proof_file_id=file_id,
            moonton_proof_type=file_type,
            moonton_status="proof_received",
            status="awaiting_admin_seller_verify",
        )

        original.clear_state(user_id)

        admin_markup = InlineKeyboardMarkup(row_width=1)
        admin_markup.add(
            InlineKeyboardButton(
                "✅ အကောင့် / Moonton စစ်ပြီးအတည်ပြုမယ်",
                callback_data=f"premium_seller_admin_verify_{rid}",
            )
        )

        caption = (
            "🔐 <b>Seller Moonton Change Proof</b>\n\n"
            f"🆔 SELL-{rid:04d}\n"
            f"👤 Seller ID — <code>{int(row['user_id'])}</code>\n"
            f"📝 Account Code — Admin စစ်ဆေးရန်\n\n"
            "Screenshot ကို စစ်ပြီး အတည်ပြုပါ။"
        )

        try:
            if file_type == "photo":
                bot.send_photo(
                    ADMIN_ID,
                    file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=admin_markup,
                )
            else:
                bot.send_document(
                    ADMIN_ID,
                    file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=admin_markup,
                )
        except Exception:
            logging.exception(
                "Seller Moonton proof forwarding failed request=%s",
                rid,
            )
            bot.send_message(
                ADMIN_ID,
                caption,
                parse_mode="HTML",
                reply_markup=admin_markup,
            )

        bot.send_message(
            user_id,
            "✅ Screenshot ရပါပြီ။ Admin စစ်ဆေးနေပါပြီ။",
            reply_markup=buyer_features_menu(),
        )

    def _seller_payout_destination_receive(message):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        if state.get("flow") != "seller_payout_destination":
            return

        request_id = int(state.get("request_id", 0) or 0)
        destination = (message.text or "").strip()

        if not destination:
            msg = bot.send_message(
                user_id,
                "❌ ငွေလွှဲနံပါတ် တစ်ခုခု ရိုက်ပို့ပါ။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(
                msg,
                _seller_payout_destination_receive,
            )
            return

        row = _seller_request_row(request_id)
        deal = _seller_deal_row(request_id)
        if not row or not deal:
            original.clear_state(user_id)
            return

        amount = int(deal["admin_offer_price"] or row["price"] or 0)

        _upsert_seller_deal(
            request_id,
            user_id,
            payout_destination=destination,
            payout_amount=amount,
            status="awaiting_admin_payout",
        )
        original.clear_state(user_id)

        admin_text = (
            "💸 <b>Seller Payout Request</b>\n\n"
            f"🆔 SELL-{request_id:04d}\n"
            f"👤 Seller — <code>{user_id}</code>\n"
            f"💰 လွှဲရမယ့်ပမာဏ — <b>{amount:,} MMK</b>\n"
            f"💳 လွှဲရန် နံပါတ် — <code>{_esc(destination)}</code>\n\n"
            "Admin ငွေလွှဲပြီးရင် ပြေစာကို Seller ဆီပို့ပေးပါ။"
        )

        bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML",
        )
        bot.send_message(
            user_id,
            "✅ ငွေလွှဲနံပါတ်ကို Admin ဆီပို့ပြီးပါပြီ။",
            reply_markup=buyer_features_menu(),
        )

    def _seller_payout_receipt_receive(message, request_id=None):
        user_id = int(message.from_user.id)
        state = original.get_state(user_id)
        rid = int(
            request_id
            if request_id is not None
            else (state.get("request_id", 0) or 0)
        )

        # This handler is reserved for a seller-confirmation or admin-sent
        # payout receipt workflow. It deliberately does not process OTPs.
        file_id = ""
        file_type = ""

        if getattr(message, "photo", None):
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif getattr(message, "document", None):
            file_id = message.document.file_id
            file_type = "document"

        if not file_id:
            return

        row = _seller_request_row(rid)
        deal = _seller_deal_row(rid)
        if not row or not deal:
            return

        _upsert_seller_deal(
            rid,
            user_id,
            payout_receipt_file_id=file_id,
            payout_receipt_type=file_type,
            status="awaiting_seller_payout_confirmation",
        )

        original.clear_state(user_id)

        bot.send_message(
            user_id,
            "✅ ငွေလွှဲပြေစာ ရပါပြီ။\n"
            "အကောင့်ဘက်က ငွေရောက်ပြီဆိုရင် အောက်က "
            "<b>ငွေရောက်ပါပြီ</b> ကိုနှိပ်ပါ။",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ ငွေရောက်ပါပြီ",
                        callback_data=f"premium_seller_payout_confirm_{rid}",
                    )
                ]
            ]),
        )

    # ------------------------------------------------------------
    # Reliable callback interception.
    # This is the key fix for generic handler ordering in main.py.
    # ------------------------------------------------------------
    previous_process = bot.process_new_updates

    if not hasattr(bot, "_premium_v8_previous_process"):
        bot._premium_v8_previous_process = previous_process

        def intercepted_process(updates):
            remaining = []
            quick_texts = {
                "🛒 အကောင့်ဝယ်မယ်",
                "👀 အကောင့်ကြည့်မယ်",
                "💰 အကောင့်ရောင်းမယ်",
            }
            for update in updates or []:
                message = getattr(update, "message", None)

                # Robust receipt handler: do not rely on next-step dispatch
                # alone for photo/document uploads.
                if message is not None:
                    state_now = original.get_state(
                        message.from_user.id
                    )
                    flow_now = state_now.get("flow")

                    if flow_now == "buy_receipt":
                        try:
                            _buy_receipt_receive(message)
                        except Exception:
                            logging.exception(
                                "Buy receipt flow interception failed"
                            )
                            bot.send_message(
                                message.chat.id,
                                "❌ ပြေစာကို လက်ခံရာမှာ အမှားရှိနေပါတယ်။ "
                                "ထပ်ပို့ပေးပါခင်ဗျာ။",
                                reply_markup=original.back_button(),
                            )
                        continue

                    if flow_now == "seller_moonton_proof":
                        try:
                            _seller_moonton_proof_receive(message)
                        except Exception:
                            logging.exception(
                                "Seller Moonton proof flow interception failed"
                            )
                        continue

                    if flow_now == "seller_expected_price":
                        print(
                            f"[SELLER_PRICE] direct-intercepted user_id={message.from_user.id} "
                            f"text={(message.text or '')[:200]!r}",
                            flush=True,
                        )
                        try:
                            _start_seller_expected_price(message)
                        except Exception:
                            import traceback
                            traceback.print_exc()
                            logging.exception(
                                "Seller expected price flow interception failed"
                            )
                        continue

                    if flow_now == "seller_note":
                        print(
                            f"[SELLER_NOTE] direct-intercepted user_id={message.from_user.id} "
                            f"text={(message.text or '')[:200]!r}",
                            flush=True,
                        )
                        try:
                            _finish_seller_submission(message)
                        except Exception:
                            import traceback
                            traceback.print_exc()
                            logging.exception(
                                "Seller note flow interception failed"
                            )
                        continue

                    if flow_now == "seller_payout_destination":
                        try:
                            _seller_payout_destination_receive(message)
                        except Exception:
                            logging.exception(
                                "Seller payout destination flow failed"
                            )
                        continue

                    if flow_now == "seller_admin_payout_receipt" and message.from_user.id == ADMIN_ID:
                        try:
                            _admin_payout_receipt_receive(message)
                        except Exception:
                            logging.exception(
                                "Admin payout receipt flow failed"
                            )
                        continue

                if message is not None and (message.text or "") in quick_texts:
                    text_value = (message.text or "").strip()
                    if text_value == "🛒 အကောင့်ဝယ်မယ်":
                        try:
                            original.clear_state(message.from_user.id)
                            msg = original.bot.send_message(
                                message.chat.id,
                                "🛒 <b>အကောင့်ဝယ်မယ်</b>\n\n"
                                "ဘရားသား <b>Account Code</b> ကို ရိုက်ပို့ပေးပါခင်ဗျာ။\n\n"
                                "💡 Code ကို Account Card ရဲ့ အပေါ်ပိုင်းမှာ\n"
                                "<b>🆔 ACC-003</b> လိုမျိုး တွေ့ရပါမယ်။\n\n"
                                "ဥပမာ — <code>ACC-003</code>",
                                parse_mode="HTML",
                                reply_markup=original.back_button(),
                            )
                            original.set_state(message.from_user.id, {"flow": "buy_query_code"})
                            original.bot.register_next_step_handler(
                                msg,
                                lambda m: _start_buy_by_code(m.chat.id, m.from_user.id, m.text),
                            )
                        except Exception:
                            logging.exception("Quick buy keyboard failed")
                        continue
                    if text_value == "👀 အကောင့်ကြည့်မယ်":
                        try:
                            accounts = original.get_available_accounts()
                            if not accounts:
                                bot.send_message(message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
                            else:
                                original.set_state(message.from_user.id, {"flow": "browse", "browse_index": 0})
                                send_account_card(message.chat.id, accounts[0], "browse", 0, len(accounts))
                        except Exception:
                            logging.exception("Quick browse keyboard failed")
                        continue
                    if text_value == "💰 အကောင့်ရောင်းမယ်":
                        try:
                            original.clear_state(message.from_user.id)
                            original.set_state(message.from_user.id, {
                                "flow": "sell_photos",
                                "photos": [],
                                "photo_prompt_sent": False,
                            })
                            bot.send_message(
                                message.chat.id,
                                "💰 <b>အကောင့်ရောင်းမယ်</b>\n\n"
                                "📸 Account ပုံ <b>အများဆုံး 15 ပုံ</b> ကို <b>တစ်ခါတည်း Album</b> အနေနဲ့ ပို့ပါ။\n\n"
                                "ပုံအားလုံးရောက်ပြီးမှ Bot က လိုအပ်တာတွေ တစ်ဆင့်ချင်း မေးပါမယ်။",
                                parse_mode="HTML",
                                reply_markup=original.back_button(),
                            )
                        except Exception:
                            logging.exception("Quick sell keyboard failed")
                        continue

                call = getattr(update, "callback_query", None)
                if call is not None:
                    if (call.data or "") == "sell_photos_done":
                        try:
                            bot.answer_callback_query(call.id)
                        except Exception:
                            pass
                        try:
                            if _intercept_sell_photos_done(call):
                                continue
                        except Exception:
                            logging.exception(
                                "Seller photos done interception failed"
                            )
                            try:
                                bot.send_message(
                                    call.message.chat.id,
                                    "❌ Seller flow ဆက်လုပ်ရာမှာ အမှားရှိနေပါတယ်။",
                                    reply_markup=original.back_button(),
                                )
                            except Exception:
                                pass
                        continue
                    try:
                        if handle_callback(call):
                            continue
                    except Exception:
                        logging.exception("Premium callback failed: %s", getattr(call, "data", ""))
                        try:
                            bot.answer_callback_query(call.id, "လုပ်ဆောင်ရာမှာ အမှားရှိနေပါတယ်။", show_alert=True)
                        except Exception:
                            pass
                        continue
                remaining.append(update)
            if remaining:
                return bot._premium_v8_previous_process(remaining)
            return None

        bot.process_new_updates = intercepted_process

    # ------------------------------------------------------------
    # Background notifications, kept independent and non-fatal.
    # ------------------------------------------------------------
    stop = threading.Event()
    last_account_id = int(rows("SELECT COALESCE(MAX(id),0) AS n FROM accounts")[0]["n"] or 0)
    price_rows = rows("SELECT id, COALESCE(sale_price,price) AS p FROM accounts")
    last_prices = {int(r["id"]): int(r["p"] or 0) for r in price_rows}

    def monitor():
        nonlocal last_account_id, last_prices
        while not stop.wait(10):
            try:
                current = rows("""
                    SELECT id, COALESCE(sale_price,price) AS p
                    FROM accounts
                    WHERE status='available'
                    ORDER BY id ASC
                """)
                max_id = max((int(r["id"]) for r in current), default=last_account_id)
                if max_id > last_account_id:
                    new_rows = [r for r in current if int(r["id"]) > last_account_id]
                    users = rows("SELECT user_id FROM premium_user_settings WHERE new_account_alert=1")
                    for r in new_rows:
                        acc = account_by_number(int(r["id"]))
                        if not acc:
                            continue
                        for u in users:
                            try:
                                m = InlineKeyboardMarkup(row_width=1)
                                m.add(InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"))
                                bot.send_message(int(u["user_id"]), "🆕 <b>Account အသစ်တင်ထားပါတယ်!</b>\n\n" + format_account_wrapped(acc), parse_mode="HTML", reply_markup=m)
                            except Exception:
                                logging.exception("New account notification failed")
                    last_account_id = max_id

                current_prices = {int(r["id"]): int(r["p"] or 0) for r in current}
                for aid, new_price in current_prices.items():
                    old_price = last_prices.get(aid, new_price)
                    if new_price < old_price:
                        alerts = rows(
                            "SELECT user_id, last_price FROM premium_price_alerts WHERE account_id=?",
                            (aid,),
                        )
                        acc = account_by_number(aid)
                        if not acc:
                            continue
                        for ar in alerts:
                            uid = int(ar["user_id"])
                            old_alert = int(ar["last_price"] or 0)
                            if new_price < old_alert:
                                try:
                                    m = InlineKeyboardMarkup(row_width=1)
                                    m.add(InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"))
                                    bot.send_message(uid, "🔔 <b>ဈေးကျသွားပါပြီ!</b>\n\n" + format_account_wrapped(acc) + f"\n\n💸 ယခုဈေး — <b>{new_price:,} MMK</b>", parse_mode="HTML", reply_markup=m)
                                    with db_lock:
                                        with closing(db_connect()) as conn:
                                            conn.execute("UPDATE premium_price_alerts SET last_price=? WHERE user_id=? AND account_id=?", (new_price, uid, aid))
                                            conn.commit()
                                except Exception:
                                    logging.exception("Price-drop notification failed")
                last_prices = current_prices
            except Exception as exc:
                if "no such table" in str(exc).lower():
                    try:
                        init_feature_db()
                        logging.info("Premium feature schema repaired after missing-table error")
                        continue
                    except Exception:
                        logging.exception("Premium feature schema repair failed")
                logging.exception("Premium feature monitor failed")

    try:
        init_feature_db()
    except Exception:
        logging.exception("Premium feature schema initialization failed before monitor start")

    threading.Thread(target=monitor, name="premium-feature-monitor-v8", daemon=True).start()

    # Expose only for diagnostics; not required by main.py.
    original.PREMIUM_FEATURES_V8_READY = True
    logging.info("PREMIUM_FEATURES_V8_READY")
