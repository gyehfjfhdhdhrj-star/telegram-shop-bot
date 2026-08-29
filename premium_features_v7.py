"""
MLBB MARKET - PREMIUM FEATURES ADDON v4
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

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

_INSTALLED = False


def install(original):
    """Install the addon onto the already-loaded main.py module."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    bot = original.bot
    ADMIN_ID = int(original.ADMIN_ID)
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
    if not hasattr(original, "_premium_v4_row_to_account"):
        original._premium_v4_row_to_account = original.row_to_account
    if not hasattr(original, "_premium_v4_format_account"):
        original._premium_v4_format_account = original.format_account
    if not hasattr(original, "_premium_v4_main_menu"):
        original._premium_v4_main_menu = original.main_menu
    if not hasattr(original, "_premium_v4_admin_keyboard"):
        original._premium_v4_admin_keyboard = original.admin_keyboard

    def row_to_account_wrapped(row):
        acc = original._premium_v4_row_to_account(row)
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
        lines = original._premium_v4_format_account(acc).split("\n")

        skin = short_skins(acc.get("skins"))
        if skin and not any("Skin အတိုချုပ်" in x for x in lines):
            lines.insert(min(3, len(lines)), f"🎨 <b>Skin အတိုချုပ် — {skin}</b>")

        if acc.get("is_verified") and not any("ADMIN စစ်ဆေးပြီး" in x for x in lines):
            lines.insert(min(4, len(lines)), "✅ <b>ADMIN စစ်ဆေးပြီး</b>")

        flash = active_flash(acc.get("db_id", 0)) if acc.get("db_id") else None
        if flash:
            deal_price, ends = flash
            seconds = max(0, int((ends - datetime.now(timezone.utc)).total_seconds()))
            mins, secs = divmod(seconds, 60)
            lines.append(f"🔥 <b>FLASH DEAL — {deal_price:,} MMK</b>  ⏰ {mins:02d}:{secs:02d}")

        return "\n".join(lines)

    original.row_to_account = row_to_account_wrapped
    original.format_account = format_account_wrapped

    def main_menu_wrapped(user_id):
        m = original._premium_v4_main_menu(user_id)
        # Keep original buttons, add only one compact entry point.
        if not any(getattr(btn, "callback_data", None) == "premium_my_account" for row in m.keyboard for btn in row):
            m.add(InlineKeyboardButton("👤 ကျွန်ုပ်၏အကောင့်", callback_data="premium_my_account"))
        if not any(getattr(btn, "callback_data", None) == "premium_more" for row in m.keyboard for btn in row):
            m.add(InlineKeyboardButton("✨ အခြား Features", callback_data="premium_more"))
        return m

    def admin_menu_wrapped():
        m = original._premium_v4_admin_keyboard()
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
            InlineKeyboardButton("🔎 အဆင့်မြင့်ရှာဖွေမယ်", callback_data="premium_advanced_search"),
            InlineKeyboardButton("✅ စစ်ဆေးပြီးအကောင့်များ", callback_data="premium_verified"),
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
            InlineKeyboardButton("⬅️ အရင်အကောင့်", callback_data=prev_cb),
            InlineKeyboardButton("နောက်အကောင့် ➡️", callback_data=next_cb),
        )
        m.row(
            InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"),
            InlineKeyboardButton("❤️ သိမ်းထားမယ်", callback_data=f"premium_fav_toggle_{acc['db_id']}"),
        )
        m.add(InlineKeyboardButton("🔔 ဈေးကျရင် အသိပေးမယ်", callback_data=f"premium_price_alert_{acc['db_id']}"))
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        return m

    def send_account_card(chat_id, acc, kind, index, total):
        if not acc:
            bot.send_message(chat_id, "❌ ဒီအကောင့် မရှိတော့ပါ။", reply_markup=original.back_button())
            return

        # Photos first, but each photo is isolated so text always survives.
        photos = [p for p in (acc.get("photos") or []) if p][:15]
        for photo in photos:
            try:
                bot.send_photo(chat_id, photo)
            except Exception:
                logging.exception("Premium photo send failed for %s", acc.get("id"))

        text = f"🎯 <b>{index + 1} / {max(1, total)}</b>\n\n{format_account_wrapped(acc)}"
        bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=account_nav_markup(kind, acc),
        )

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
            bot.send_message(call.message.chat.id, "❌ ကြည့်ရန်အကောင့် မရှိသေးပါ။", reply_markup=buyer_features_menu())
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
        if data == "premium_more":
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "✨ <b>အသုံးဝင်တဲ့ Features</b>\n\nလိုချင်တာကို ရွေးပါ။", parse_mode="HTML", reply_markup=buyer_features_menu())
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
                bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=buyer_features_menu())
            else:
                added = toggle_favorite(call.from_user.id, aid)
                bot.send_message(
                    call.message.chat.id,
                    f"❤️ <b>{acc['id']}</b> ကို သိမ်းထားလိုက်ပါပြီ။" if added else f"💔 <b>{acc['id']}</b> ကို သိမ်းထားတာ ဖြုတ်လိုက်ပါပြီ။",
                    parse_mode="HTML",
                    reply_markup=buyer_features_menu(),
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
                bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=buyer_features_menu())
            else:
                acc = account_by_number(aid)
                bot.send_message(
                    call.message.chat.id,
                    f"🔔 <b>{acc['id']}</b> ဈေးကျရင် အသိပေးပါမယ်။" if enabled else f"🔕 <b>{acc['id']}</b> ရဲ့ ဈေးကျအသိပေးချက် ပိတ်လိုက်ပါပြီ။",
                    parse_mode="HTML",
                    reply_markup=buyer_features_menu(),
                )
            return True

        if data.startswith("premium_fast_buy_"):
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_fast_buy_", "", 1)
            acc = account_by_text(aid)
            if not acc or acc.get("status") != "available":
                bot.send_message(call.message.chat.id, "❌ ဒီအကောင့် လက်ရှိ ဝယ်ယူလို့မရတော့ပါ။", reply_markup=buyer_features_menu())
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
                "🔎 <b>အဆင့်မြင့်ရှာဖွေမယ်</b>\n\n"
                "ဒီလိုရေးပါ — <code>Skin | အနည်းဆုံးဈေး | အများဆုံးဈေး</code>\n\n"
                "ဥပမာ — <code>Collector | 100000 | 200000</code>\n"
                "Skin မလိုချင်ရင် — <code>Any | 0 | 150000</code>",
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
                mins, secs = divmod(remain, 60)
                discount_amount = max(0, original_price - deal_price)
                discount_pct = int(round(discount_amount * 100 / original_price)) if original_price > 0 else 0
                text_card = (
                    "🔥 <b>အထူးစပရှယ် လျော့စျေးအကောင့်</b>\n\n"
                    f"🆔 <b>{acc['id']}</b>\n"
                    f"💰 အရင်ဈေး — <s>{original_price:,} MMK</s>\n"
                    f"🔥 ယခုဈေး — <b>{deal_price:,} MMK</b>\n"
                    f"🎟️ အကောင့်လျော့စျေးကူပွန် — <b>-{discount_amount:,} MMK ({discount_pct}%)</b>\n"
                    f"⏰ ကုန်ဆုံးချိန် — <b>{mins:02d}:{secs:02d}</b>\n\n"
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
                m.add(InlineKeyboardButton("🔔 ဈေးကျရင် အသိပေးမယ်", callback_data=f"premium_price_alert_{acc['db_id']}"))
                m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
                bot.send_message(call.message.chat.id, text_card, parse_mode="HTML", reply_markup=m)
            return True

        if data.startswith("premium_flash_buy_"):
            bot.answer_callback_query(call.id)
            aid = data.replace("premium_flash_buy_", "", 1)
            acc = account_by_text(aid)
            deal = active_flash(acc["db_id"]) if acc else None
            if not acc or not deal:
                bot.send_message(call.message.chat.id, "❌ Flash Deal သက်တမ်းကုန်သွားပါပြီ။", reply_markup=buyer_features_menu())
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
        parts = [p.strip() for p in raw.split("|", 2)]
        if len(parts) != 3:
            msg = bot.send_message(message.chat.id, "❌ Format မမှန်ပါ။\n<code>Collector | 100000 | 200000</code>", parse_mode="HTML", reply_markup=original.back_button())
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
            bot.send_message(message.chat.id, "❌ အနီးစပ်ဆုံး Account မတွေ့သေးပါ။", reply_markup=buyer_features_menu())
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
    # Reliable callback interception.
    # This is the key fix for generic handler ordering in main.py.
    # ------------------------------------------------------------
    previous_process = bot.process_new_updates

    if not hasattr(bot, "_premium_v4_previous_process"):
        bot._premium_v4_previous_process = previous_process

        def intercepted_process(updates):
            remaining = []
            for update in updates or []:
                call = getattr(update, "callback_query", None)
                if call is not None:
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
                return bot._premium_v4_previous_process(remaining)
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

    threading.Thread(target=monitor, name="premium-feature-monitor-v4", daemon=True).start()

    # Expose only for diagnostics; not required by main.py.
    original.PREMIUM_FEATURES_V4_READY = True
    logging.info("PREMIUM_FEATURES_V4_READY")
