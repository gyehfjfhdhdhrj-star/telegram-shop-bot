"""
MLBB MARKET - PREMIUM FEATURES ADDON v3

This file is intentionally separate from main.py and supabase_launcher.py.
It is loaded by premium_start_v3.py after supabase_launcher.py has loaded main.py.

Existing main.py source is not edited on disk.
Existing Supabase persistence code is not edited by this module.

Features:
- Fast Buy
- Flash Deal (admin management + buyer display)
- Price Drop Alert
- Verified Account (admin toggle + buyer list)
- My Account
- New Accounts
- Advanced Search (nearest matches)
- New Account Notification (user toggle + admin stats)
- Favorites
- Clean one-account-at-a-time navigation
- Existing account photo + text display kept together
- No message deletion/cleanup
"""

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import threading

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


_INSTALLED = False
_CURRENT = threading.local()


def install(original):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    bot = original.bot
    ADMIN_ID = original.ADMIN_ID
    db_lock = original.db_lock
    db_connect = original.db_connect
    closing = original.closing

    # ------------------------------------------------------------
    # Database additions only. No DROP/DELETE of existing tables.
    # ------------------------------------------------------------
    def feature_init_db():
        with db_lock:
            with closing(db_connect()) as conn:
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
                if "is_verified" not in cols:
                    conn.execute(
                        "ALTER TABLE accounts ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
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
                    CREATE TABLE IF NOT EXISTS premium_view_history (
                        user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, account_id)
                    )
                """)
                conn.commit()

    feature_init_db()

    def rows(sql, params=()):
        with db_lock:
            with closing(db_connect()) as conn:
                return conn.execute(sql, params).fetchall()

    def account(aid):
        try:
            return original.get_account_by_text_id(original.make_account_id(int(aid)))
        except Exception:
            return None

    def record_view(user_id, account_id):
        try:
            with db_lock:
                with closing(db_connect()) as conn:
                    conn.execute("""
                        INSERT INTO premium_view_history(user_id, account_id, viewed_at)
                        VALUES(?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, account_id)
                        DO UPDATE SET viewed_at=CURRENT_TIMESTAMP
                    """, (int(user_id), int(account_id)))
                    conn.commit()
        except Exception:
            pass

    def favorites(user_id):
        result = rows(
            "SELECT account_id FROM premium_favorites WHERE user_id=? ORDER BY created_at ASC",
            (int(user_id),),
        )
        return [int(r["account_id"]) for r in result]

    def toggle_favorite(user_id, account_id):
        with db_lock:
            with closing(db_connect()) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM premium_favorites WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()
                if exists:
                    conn.execute(
                        "DELETE FROM premium_favorites WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    state = False
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO premium_favorites(user_id, account_id) VALUES(?, ?)",
                        (int(user_id), int(account_id)),
                    )
                    state = True
                conn.commit()
                return state

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
        acc = account(account_id)
        if not acc:
            return None
        current = int(acc.get("effective_price") or acc.get("price") or 0)
        with db_lock:
            with closing(db_connect()) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM premium_price_alerts WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()
                if exists:
                    conn.execute(
                        "DELETE FROM premium_price_alerts WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    enabled = False
                else:
                    conn.execute("""
                        INSERT OR REPLACE INTO premium_price_alerts(user_id, account_id, last_price)
                        VALUES(?, ?, ?)
                    """, (int(user_id), int(account_id), current))
                    enabled = True
                conn.commit()
        return enabled

    def set_verified(account_id, enabled):
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute(
                    "UPDATE accounts SET is_verified=? WHERE id=?",
                    (1 if enabled else 0, int(account_id)),
                )
                conn.commit()

    def is_verified(account_id):
        result = rows("SELECT is_verified FROM accounts WHERE id=?", (int(account_id),))
        return bool(result and int(result[0]["is_verified"] or 0))

    def active_flash(account_id):
        result = rows(
            "SELECT deal_price, ends_at FROM premium_flash_deals WHERE account_id=?",
            (int(account_id),),
        )
        if not result:
            return None
        try:
            end = datetime.fromisoformat(str(result[0]["ends_at"]).replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end <= datetime.now(timezone.utc):
                with db_lock:
                    with closing(db_connect()) as conn:
                        conn.execute("DELETE FROM premium_flash_deals WHERE account_id=?", (int(account_id),))
                        conn.commit()
                return None
            return int(result[0]["deal_price"]), end
        except Exception:
            return None

    def set_flash(account_id, price, minutes):
        end = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute("""
                    INSERT INTO premium_flash_deals(account_id, deal_price, ends_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(account_id)
                    DO UPDATE SET deal_price=excluded.deal_price, ends_at=excluded.ends_at
                """, (int(account_id), int(price), end.isoformat()))
                conn.commit()

    # ------------------------------------------------------------
    # Account conversion/display: preserve original output first.
    # ------------------------------------------------------------
    if not hasattr(original, "_premium_v3_row_to_account"):
        original._premium_v3_row_to_account = original.row_to_account
    if not hasattr(original, "_premium_v3_format_account"):
        original._premium_v3_format_account = original.format_account
    if not hasattr(original, "_premium_v3_send_account_photos"):
        original._premium_v3_send_account_photos = original.send_account_photos
    if not hasattr(original, "_premium_v3_main_menu"):
        original._premium_v3_main_menu = original.main_menu
    if not hasattr(original, "_premium_v3_admin_keyboard"):
        original._premium_v3_admin_keyboard = original.admin_keyboard
    if not hasattr(original, "_premium_v3_account_keyboard"):
        original._premium_v3_account_keyboard = original.account_action_keyboard
    if not hasattr(original, "_premium_v3_search_results"):
        original._premium_v3_search_results = original.send_search_results

    def row_to_account_wrapped(row):
        acc = original._premium_v3_row_to_account(row)
        try:
            keys = row.keys()
            acc["is_verified"] = int(row["is_verified"] or 0) if "is_verified" in keys else 0
        except Exception:
            acc["is_verified"] = 0
        return acc

    def short_skin_text(raw):
        text = str(raw or "").replace("\n", " ").strip()
        return text if len(text) <= 100 else text[:97] + "..."

    def format_account_wrapped(acc):
        base = original._premium_v3_format_account(acc)
        lines = base.split("\n")

        skin = short_skin_text(acc.get("skins"))
        if skin and not any("Skin အတိုချုပ်" in line for line in lines):
            lines.insert(min(3, len(lines)), f"🎨 <b>Skin အတိုချုပ် — {skin}</b>")

        if acc.get("is_verified") and not any("ADMIN စစ်ဆေးပြီး" in line for line in lines):
            lines.insert(min(4, len(lines)), "✅ <b>ADMIN စစ်ဆေးပြီး</b>")

        flash = active_flash(acc.get("db_id", 0)) if acc.get("db_id") else None
        if flash and not any("FLASH DEAL" in line for line in lines):
            deal_price, end = flash
            remain = max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
            mins, secs = divmod(remain, 60)
            lines.append(f"🔥 <b>FLASH DEAL — {deal_price:,} MMK</b>  ⏰ {mins:02d}:{secs:02d}")

        return "\n".join(lines)

    original.row_to_account = row_to_account_wrapped
    original.format_account = format_account_wrapped

    # ------------------------------------------------------------
    # Navigation keyboards
    # ------------------------------------------------------------
    def nav_markup(prev_cb, next_cb, extra_rows=None):
        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton("⬅️ အရင်အကောင့်", callback_data=prev_cb),
            InlineKeyboardButton("နောက်အကောင့် ➡️", callback_data=next_cb),
        )
        if extra_rows:
            for row in extra_rows:
                m.row(*row)
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        return m

    def account_feature_markup(acc, kind, user_id=None):
        if kind == "browse":
            prev_cb, next_cb = "premium_browse_prev", "premium_browse_next"
        elif kind == "search":
            prev_cb, next_cb = "premium_search_prev", "premium_search_next"
        elif kind == "favorites":
            prev_cb, next_cb = "premium_fav_prev", "premium_fav_next"
        elif kind == "new":
            prev_cb, next_cb = "premium_new_prev", "premium_new_next"
        elif kind == "verified":
            prev_cb, next_cb = "premium_ver_prev", "premium_ver_next"
        else:
            prev_cb, next_cb = "premium_browse_prev", "premium_browse_next"

        extra = [
            [
                InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"),
                InlineKeyboardButton("❤️ သိမ်းထားမယ်", callback_data=f"premium_fav_toggle_{acc['db_id']}"),
            ],
            [InlineKeyboardButton("🔔 ဈေးကျရင် အသိပေးမယ်", callback_data=f"premium_price_alert_{acc['db_id']}")],
        ]
        return nav_markup(prev_cb, next_cb, extra)

    def send_account_card(chat_id, acc, kind="browse", index=0, total=1, include_navigation=True):
        if not acc:
            bot.send_message(chat_id, "❌ ဒီအကောင့် မရှိတော့ပါ။", reply_markup=original.back_button())
            return

        record_view(chat_id, acc.get("db_id", 0))
        photos = [p for p in (acc.get("photos") or []) if p][:15]

        # Explicitly send the stored URLs/photo IDs, then ALWAYS send the text card.
        # This avoids the old behavior where a media-group exception could prevent the
        # account text from appearing in the same flow.
        for photo in photos:
            try:
                bot.send_photo(chat_id, photo)
            except Exception:
                # Do not stop the text card because one photo failed.
                pass

        text = f"🎯 <b>{index + 1} / {total}</b>\n\n{format_account_wrapped(acc)}"
        markup = account_feature_markup(acc, kind, chat_id) if include_navigation else original._premium_v3_account_keyboard(acc, admin=False, include_menu=True)
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    def send_account_photos_wrapped(chat_id, acc, include_menu=True):
        # This is used by the original browse/detail flow.
        user_id = getattr(_CURRENT, "user_id", chat_id)
        state = original.get_state(user_id)
        kind = state.get("premium_kind")
        if kind:
            ids = state.get("premium_ids", [])
            idx = int(state.get("premium_index", 0)) if ids else 0
            send_account_card(chat_id, acc, kind=kind, index=idx, total=len(ids), include_navigation=True)
            return

        # Plain original browse: still preserve text and add reliable prev/next.
        idx = int(state.get("browse_index", 0))
        all_accounts = original.get_available_accounts()
        send_account_card(chat_id, acc, kind="browse", index=idx, total=max(1, len(all_accounts)), include_navigation=True)

    original.send_account_photos = send_account_photos_wrapped

    # ------------------------------------------------------------
    # Main/Admin menus: keep ALL existing buttons and add only one
    # compact entry point for each side.
    # ------------------------------------------------------------
    def main_menu_wrapped(user_id):
        m = original._premium_v3_main_menu(user_id)
        m.add(
            InlineKeyboardButton("👤 ကျွန်ုပ်၏အကောင့်", callback_data="premium_my_account"),
            InlineKeyboardButton("✨ အခြား Features", callback_data="premium_more"),
        )
        return m

    def admin_keyboard_wrapped():
        m = original._premium_v3_admin_keyboard()
        m.add(InlineKeyboardButton("✨ Premium Features စီမံမယ်", callback_data="premium_admin_tools"))
        return m

    original.main_menu = main_menu_wrapped
    original.admin_keyboard = admin_keyboard_wrapped

    # ------------------------------------------------------------
    # Compact buyer menu. Admin-only management is NOT shown here.
    # ------------------------------------------------------------
    def buyer_more_markup():
        m = InlineKeyboardMarkup(row_width=2)
        m.add(
            InlineKeyboardButton("❤️ သိမ်းထားတဲ့အကောင့်များ", callback_data="premium_favorites"),
            InlineKeyboardButton("🆕 အသစ်တင်ထားတဲ့အကောင့်များ", callback_data="premium_new_accounts"),
            InlineKeyboardButton("🔎 အဆင့်မြင့်ရှာဖွေမယ်", callback_data="premium_advanced_search"),
            InlineKeyboardButton("✅ စစ်ဆေးပြီးအကောင့်များ", callback_data="premium_verified"),
            InlineKeyboardButton("🔔 အသစ်တင်အသိပေးချက်", callback_data="premium_new_alert"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        return m

    # ------------------------------------------------------------
    # Compact admin-only premium management menu.
    # ------------------------------------------------------------
    def admin_feature_markup():
        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton("🔥 Flash Deal စီမံမယ်", callback_data="premium_admin_flash_list"),
            InlineKeyboardButton("✅ Verified စီမံမယ်", callback_data="premium_admin_verified_list"),
            InlineKeyboardButton("🔔 အသစ်တင်အသိပေးချက် စီမံမယ်", callback_data="premium_admin_alert_stats"),
            InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"),
        )
        return m

    # ------------------------------------------------------------
    # Generic premium list state helpers.
    # ------------------------------------------------------------
    def make_ids(accounts):
        return [a["id"] for a in accounts]

    def show_state_list(chat_id, user_id, ids, kind):
        if not ids:
            bot.send_message(chat_id, "❌ ဒီအမျိုးအစားအကောင့် မရှိသေးပါ။", reply_markup=buyer_more_markup())
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
        _CURRENT.user_id = user_id
        acc = original.get_account_by_text_id(ids[0])
        send_account_card(chat_id, acc, kind=kind, index=0, total=len(ids), include_navigation=True)

    def nav_state(call, direction):
        st = original.get_state(call.from_user.id)
        ids = st.get("premium_ids", [])
        if not ids:
            bot.send_message(call.message.chat.id, "❌ ကြည့်ရန်အကောင့် မရှိသေးပါ။", reply_markup=buyer_more_markup())
            return
        idx = int(st.get("premium_index", 0)) + int(direction)
        idx %= len(ids)
        st["premium_index"] = idx
        original.set_state(call.from_user.id, st)
        _CURRENT.user_id = call.from_user.id
        acc = original.get_account_by_text_id(ids[idx])
        send_account_card(
            call.message.chat.id,
            acc,
            kind=st.get("premium_kind", "browse"),
            index=idx,
            total=len(ids),
            include_navigation=True,
        )

    # ------------------------------------------------------------
    # Existing browse flow: replace only the display/navigation wrapper.
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_browse_prev")
    def premium_browse_prev(call):
        bot.answer_callback_query(call.id)
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
            return
        st = original.get_state(call.from_user.id)
        idx = int(st.get("browse_index", 0)) - 1
        idx %= len(accounts)
        original.set_state(call.from_user.id, {"flow": "browse", "browse_index": idx})
        _CURRENT.user_id = call.from_user.id
        send_account_card(call.message.chat.id, accounts[idx], "browse", idx, len(accounts), True)

    @bot.callback_query_handler(func=lambda c: c.data == "premium_browse_next")
    def premium_browse_next(call):
        bot.answer_callback_query(call.id)
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
            return
        st = original.get_state(call.from_user.id)
        idx = int(st.get("browse_index", 0)) + 1
        idx %= len(accounts)
        original.set_state(call.from_user.id, {"flow": "browse", "browse_index": idx})
        _CURRENT.user_id = call.from_user.id
        send_account_card(call.message.chat.id, accounts[idx], "browse", idx, len(accounts), True)

    # Intercept browse_0 and all numbered browse callbacks before the old sender.
    @bot.callback_query_handler(func=lambda c: c.data.startswith("browse_") and c.data != "browse_next")
    def premium_browse_override(call):
        bot.answer_callback_query(call.id)
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
            return
        try:
            idx = int(call.data.replace("browse_", ""))
        except ValueError:
            idx = 0
        idx %= len(accounts)
        original.set_state(call.from_user.id, {"flow": "browse", "browse_index": idx})
        _CURRENT.user_id = call.from_user.id
        send_account_card(call.message.chat.id, accounts[idx], "browse", idx, len(accounts), True)

    # Also override browse_next so old cleanup/display does not hide text.
    @bot.callback_query_handler(func=lambda c: c.data == "browse_next")
    def premium_browse_next_legacy(call):
        bot.answer_callback_query(call.id)
        accounts = original.get_available_accounts()
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ လောလောဆယ် အကောင့် မရှိသေးပါ။", reply_markup=original.back_button())
            return
        st = original.get_state(call.from_user.id)
        idx = (int(st.get("browse_index", 0)) + 1) % len(accounts)
        original.set_state(call.from_user.id, {"flow": "browse", "browse_index": idx})
        _CURRENT.user_id = call.from_user.id
        send_account_card(call.message.chat.id, accounts[idx], "browse", idx, len(accounts), True)

    # ------------------------------------------------------------
    # Replace existing multi-result search display with one-at-a-time.
    # ------------------------------------------------------------
    def send_search_results_wrapped(chat_id, results):
        if not results:
            bot.send_message(chat_id, "❌ ကိုက်ညီတဲ့ Account မတွေ့ပါသေးပါ။", reply_markup=original.back_button())
            return
        ids = make_ids(results)
        original.set_state(
            chat_id,
            {
                "flow": "premium_search",
                "premium_ids": ids,
                "premium_index": 0,
                "premium_kind": "search",
            },
        )
        _CURRENT.user_id = chat_id
        acc = original.get_account_by_text_id(ids[0])
        send_account_card(chat_id, acc, "search", 0, len(ids), True)

    original.send_search_results = send_search_results_wrapped

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_search_prev", "premium_search_next"))
    def premium_search_nav(call):
        bot.answer_callback_query(call.id)
        nav_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------
    # More Features + My Account
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_more")
    def premium_more(call):
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "✨ <b>အသုံးဝင်တဲ့ Features</b>\n\nလိုချင်တာကို ရွေးပါ။",
            parse_mode="HTML",
            reply_markup=buyer_more_markup(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "premium_my_account")
    def premium_my_account(call):
        bot.answer_callback_query(call.id)
        uid = call.from_user.id
        fav_count = len(favorites(uid))
        alert = "ဖွင့်ထားပါတယ် ✅" if new_alert_enabled(uid) else "ပိတ်ထားပါတယ် ❌"
        text = (
            "👤 <b>ကျွန်ုပ်၏အကောင့်</b>\n\n"
            f"🆔 User ID — <code>{uid}</code>\n"
            f"❤️ သိမ်းထားတဲ့အကောင့် — <b>{fav_count}</b> ခု\n"
            f"🔔 အသစ်တင်အသိပေးချက် — <b>{alert}</b>"
        )
        m = InlineKeyboardMarkup(row_width=2)
        m.add(
            InlineKeyboardButton("❤️ သိမ်းထားတာကြည့်မယ်", callback_data="premium_favorites"),
            InlineKeyboardButton("🆕 အသစ်တင်တာကြည့်မယ်", callback_data="premium_new_accounts"),
            InlineKeyboardButton("🔔 အသိပေးချက်ပြောင်းမယ်", callback_data="premium_new_alert"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=m)

    # ------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_favorites")
    def premium_favorites(call):
        bot.answer_callback_query(call.id)
        ids = [original.make_account_id(x) for x in favorites(call.from_user.id) if account(x)]
        show_state_list(call.message.chat.id, call.from_user.id, ids, "favorites")

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_fav_prev", "premium_fav_next"))
    def premium_fav_nav(call):
        bot.answer_callback_query(call.id)
        nav_state(call, -1 if call.data.endswith("prev") else 1)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_fav_toggle_"))
    def premium_fav_toggle(call):
        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_fav_toggle_", "", 1))
        acc = account(aid)
        if not acc:
            bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=buyer_more_markup())
            return
        state = toggle_favorite(call.from_user.id, aid)
        bot.send_message(
            call.message.chat.id,
            f"❤️ <b>{acc['id']}</b> ကို သိမ်းထားလိုက်ပါပြီ။" if state else f"💔 <b>{acc['id']}</b> ကို သိမ်းထားတာ ဖြုတ်လိုက်ပါပြီ။",
            parse_mode="HTML",
            reply_markup=buyer_more_markup(),
        )

    # ------------------------------------------------------------
    # New accounts
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_new_accounts")
    def premium_new_accounts(call):
        bot.answer_callback_query(call.id)
        accs = original.get_available_accounts()
        # Newest first, while display navigation remains normal.
        accs = list(reversed(accs))
        show_state_list(call.message.chat.id, call.from_user.id, make_ids(accs), "new")

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_new_prev", "premium_new_next"))
    def premium_new_nav(call):
        bot.answer_callback_query(call.id)
        nav_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------
    # Verified buyer list
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_verified")
    def premium_verified(call):
        bot.answer_callback_query(call.id)
        verified_accs = [a for a in original.get_available_accounts() if is_verified(a["db_id"])]
        show_state_list(call.message.chat.id, call.from_user.id, make_ids(verified_accs), "verified")

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_ver_prev", "premium_ver_next"))
    def premium_ver_nav(call):
        bot.answer_callback_query(call.id)
        nav_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------
    # Price alert
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_price_alert_"))
    def premium_price_alert(call):
        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_price_alert_", "", 1))
        state = toggle_price_alert(call.from_user.id, aid)
        if state is None:
            bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=buyer_more_markup())
            return
        acc = account(aid)
        bot.send_message(
            call.message.chat.id,
            f"🔔 <b>{acc['id']}</b> ဈေးကျရင် အသိပေးပါမယ်။" if state else f"🔕 <b>{acc['id']}</b> ဈေးကျအသိပေးချက်ကို ပိတ်လိုက်ပါပြီ။",
            parse_mode="HTML",
            reply_markup=buyer_more_markup(),
        )

    # ------------------------------------------------------------
    # Fast buy
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_fast_buy_"))
    def premium_fast_buy(call):
        bot.answer_callback_query(call.id)
        aid = call.data.replace("premium_fast_buy_", "", 1)
        acc = original.get_account_by_text_id(aid)
        if not acc or acc.get("status") != "available":
            bot.send_message(call.message.chat.id, "❌ ဒီအကောင့် လက်ရှိ ဝယ်ယူလို့မရတော့ပါ။", reply_markup=buyer_more_markup())
            return
        deal = active_flash(acc["db_id"])
        price = deal[0] if deal else int(acc.get("effective_price") or acc["price"])
        m = InlineKeyboardMarkup(row_width=1)
        if original.ADMIN_USERNAME:
            m.add(InlineKeyboardButton("👨‍💻 Admin ကို တိုက်ရိုက်ဆက်သွယ်မယ်", url=f"https://t.me/{original.ADMIN_USERNAME}"))
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        bot.send_message(
            call.message.chat.id,
            "⚡ <b>အမြန်ဝယ်ယူမယ်</b>\n\n"
            + format_account_wrapped(acc)
            + f"\n\n💰 <b>ဝယ်ဈေး — {price:,} MMK</b>\n\n"
            "ဝယ်ယူဖို့ Admin ကို တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။",
            parse_mode="HTML",
            reply_markup=m,
        )

    # ------------------------------------------------------------
    # Advanced search - nearest match + price range.
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_advanced_search")
    def premium_advanced_search(call):
        bot.answer_callback_query(call.id)
        original.set_state(call.from_user.id, {"flow": "premium_advanced_search"})
        msg = bot.send_message(
            call.message.chat.id,
            "🔎 <b>အဆင့်မြင့်ရှာဖွေမယ်</b>\n\n"
            "ဒီပုံစံနဲ့ ရိုက်ပို့ပါ — <code>Skin | အနည်းဆုံးဈေး | အများဆုံးဈေး</code>\n\n"
            "ဥပမာ — <code>Collector | 100000 | 200000</code>\n"
            "Skin မသတ်မှတ်ချင်ရင် — <code>Any | 0 | 150000</code>",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(msg, premium_advanced_search_receive)

    def premium_advanced_search_receive(message):
        raw = (message.text or "").strip()
        parts = [x.strip() for x in raw.split("|", 2)]
        if len(parts) != 3:
            msg = bot.send_message(message.chat.id, "❌ Format မမှန်ပါ။ <code>Collector | 100000 | 200000</code>", parse_mode="HTML")
            bot.register_next_step_handler(msg, premium_advanced_search_receive)
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
            bot.send_message(message.chat.id, "❌ ဈေးနှုန်း မမှန်ပါ။", reply_markup=original.back_button())
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
        ids = [acc["id"] for _, acc in scored]
        if not ids:
            bot.send_message(message.chat.id, "❌ အနီးစပ်ဆုံး Account မတွေ့သေးပါ။", reply_markup=buyer_more_markup())
            return

        show_state_list(message.chat.id, message.from_user.id, ids, "search")

    # ------------------------------------------------------------
    # User-facing new-account alert toggle.
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_new_alert")
    def premium_new_alert(call):
        bot.answer_callback_query(call.id)
        enabled = not new_alert_enabled(call.from_user.id)
        set_new_alert(call.from_user.id, enabled)
        bot.send_message(
            call.message.chat.id,
            "🔔 <b>အသစ်တင်အကောင့် အသိပေးချက် ဖွင့်ပြီးပါပြီ။</b>" if enabled else "🔕 <b>အသစ်တင်အကောင့် အသိပေးချက် ပိတ်ပြီးပါပြီ။</b>",
            parse_mode="HTML",
            reply_markup=buyer_more_markup(),
        )

    # ------------------------------------------------------------
    # Admin-only tools.
    # ------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_tools")
    def premium_admin_tools(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(ADMIN_ID, "✨ <b>Premium Features စီမံမယ်</b>", parse_mode="HTML", reply_markup=admin_feature_markup())

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_flash_list")
    def premium_admin_flash_list(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        m = InlineKeyboardMarkup(row_width=1)
        for acc in original.get_admin_accounts(status="available")[:50]:
            deal = active_flash(acc["db_id"])
            label = f"🔥 {acc['id']} — {deal[0]:,} MMK" if deal else f"💰 {acc['id']} — {acc['effective_price']:,} MMK"
            m.add(InlineKeyboardButton(label, callback_data=f"premium_admin_flash_{acc['id']}"))
        m.add(InlineKeyboardButton("🔙 Premium Features", callback_data="premium_admin_tools"))
        bot.send_message(ADMIN_ID, "🔥 Flash Deal တင်/ပြင်မယ့် Account ကို ရွေးပါ။", reply_markup=m)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_admin_flash_"))
    def premium_admin_flash_start(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        aid = call.data.replace("premium_admin_flash_", "", 1)
        acc = original.get_account_by_text_id(aid)
        if not acc:
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_feature_markup())
            return
        original.set_state(ADMIN_ID, {"flow": "premium_admin_flash", "premium_flash_account": aid})
        msg = bot.send_message(
            ADMIN_ID,
            f"🔥 <b>{aid}</b> Flash Deal\n\n<code>Deal ဈေး | မိနစ်</code>\nဥပမာ — <code>90000 | 60</code>",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(msg, premium_admin_flash_receive)

    def premium_admin_flash_receive(message):
        if message.from_user.id != ADMIN_ID:
            return
        st = original.get_state(ADMIN_ID)
        if st.get("flow") != "premium_admin_flash":
            return
        parts = [x.strip() for x in (message.text or "").split("|", 1)]
        if len(parts) != 2:
            msg = bot.send_message(ADMIN_ID, "❌ Format မမှန်ပါ။ <code>90000 | 60</code>", parse_mode="HTML")
            bot.register_next_step_handler(msg, premium_admin_flash_receive)
            return
        try:
            price = int(parts[0].replace(",", "").replace(" ", ""))
            minutes = int(parts[1])
            if price <= 0 or minutes <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(ADMIN_ID, "❌ ဈေး/အချိန် မမှန်ပါ။")
            bot.register_next_step_handler(msg, premium_admin_flash_receive)
            return
        aid = st.get("premium_flash_account")
        acc = original.get_account_by_text_id(aid)
        if not acc:
            original.clear_state(ADMIN_ID)
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_feature_markup())
            return
        set_flash(acc["db_id"], price, minutes)
        original.clear_state(ADMIN_ID)
        bot.send_message(ADMIN_ID, f"✅ <b>{aid}</b> Flash Deal တင်ပြီးပါပြီ။\n\n🔥 {price:,} MMK\n⏰ {minutes} မိနစ်", parse_mode="HTML", reply_markup=admin_feature_markup())

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_verified_list")
    def premium_admin_verified_list(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        m = InlineKeyboardMarkup(row_width=1)
        for acc in original.get_admin_accounts()[:50]:
            icon = "✅" if is_verified(acc["db_id"]) else "⬜"
            m.add(InlineKeyboardButton(f"{icon} {acc['id']}", callback_data=f"premium_admin_verify_{acc['db_id']}"))
        m.add(InlineKeyboardButton("🔙 Premium Features", callback_data="premium_admin_tools"))
        bot.send_message(ADMIN_ID, "✅ Verified လုပ်/ဖြုတ်မယ့် Account ကို ရွေးပါ။", reply_markup=m)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_admin_verify_"))
    def premium_admin_verify(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_admin_verify_", "", 1))
        acc = account(aid)
        if not acc:
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=admin_feature_markup())
            return
        enabled = not is_verified(aid)
        set_verified(aid, enabled)
        bot.send_message(
            ADMIN_ID,
            f"✅ <b>{acc['id']}</b> ကို Verified လုပ်ပြီးပါပြီ။" if enabled else f"❌ <b>{acc['id']}</b> Verified ဖြုတ်ပြီးပါပြီ။",
            parse_mode="HTML",
            reply_markup=admin_feature_markup(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_alert_stats")
    def premium_admin_alert_stats(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        new_users = rows("SELECT COUNT(*) AS n FROM premium_user_settings WHERE new_account_alert=1")[0]["n"]
        price_users = rows("SELECT COUNT(DISTINCT user_id) AS n FROM premium_price_alerts")[0]["n"]
        bot.send_message(
            ADMIN_ID,
            "🔔 <b>အသိပေးချက် အချက်အလက်</b>\n\n"
            f"🆕 အသစ်တင်အသိပေးချက် ဖွင့်ထားသူ — <b>{new_users}</b> ယောက်\n"
            f"💸 ဈေးကျအသိပေးချက် အသုံးပြုသူ — <b>{price_users}</b> ယောက်",
            parse_mode="HTML",
            reply_markup=admin_feature_markup(),
        )

    # ------------------------------------------------------------
    # Background notifications. Failures never stop the bot.
    # ------------------------------------------------------------
    stop = threading.Event()
    baseline = rows("SELECT COALESCE(MAX(id),0) AS max_id FROM accounts")[0]["max_id"]
    last_account_id = int(baseline or 0)
    price_rows = rows("SELECT id, COALESCE(sale_price,price) AS p FROM accounts")
    last_prices = {int(r["id"]): int(r["p"] or 0) for r in price_rows}

    def feature_monitor():
        nonlocal last_account_id, last_prices
        while not stop.wait(10):
            try:
                current = rows("""
                    SELECT id, COALESCE(sale_price,price) AS p
                    FROM accounts WHERE status='available' ORDER BY id ASC
                """)
                max_id = max((int(r["id"]) for r in current), default=last_account_id)

                if max_id > last_account_id:
                    new_rows = [r for r in current if int(r["id"]) > last_account_id]
                    users = rows("SELECT user_id FROM premium_user_settings WHERE new_account_alert=1")
                    for r in new_rows:
                        acc = account(int(r["id"]))
                        if not acc:
                            continue
                        for u in users:
                            try:
                                m = InlineKeyboardMarkup(row_width=1)
                                m.add(InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"))
                                bot.send_message(
                                    int(u["user_id"]),
                                    "🆕 <b>Account အသစ်တင်ထားပါတယ်!</b>\n\n" + format_account_wrapped(acc),
                                    parse_mode="HTML",
                                    reply_markup=m,
                                )
                            except Exception:
                                pass
                    last_account_id = max_id

                current_prices = {int(r["id"]): int(r["p"] or 0) for r in current}
                for aid, new_price in current_prices.items():
                    old_price = last_prices.get(aid, new_price)
                    if new_price < old_price:
                        alert_rows = rows(
                            "SELECT user_id, last_price FROM premium_price_alerts WHERE account_id=?",
                            (aid,),
                        )
                        acc = account(aid)
                        if not acc:
                            continue
                        for ar in alert_rows:
                            uid = int(ar["user_id"])
                            old_alert = int(ar["last_price"] or 0)
                            if new_price < old_alert:
                                try:
                                    m = InlineKeyboardMarkup(row_width=1)
                                    m.add(InlineKeyboardButton("⚡ အမြန်ဝယ်မယ်", callback_data=f"premium_fast_buy_{acc['id']}"))
                                    bot.send_message(
                                        uid,
                                        "🔔 <b>ဈေးကျသွားပါပြီ!</b>\n\n" + format_account_wrapped(acc) + f"\n\n💸 ယခုဈေး — <b>{new_price:,} MMK</b>",
                                        parse_mode="HTML",
                                        reply_markup=m,
                                    )
                                    with db_lock:
                                        with closing(db_connect()) as conn:
                                            conn.execute(
                                                "UPDATE premium_price_alerts SET last_price=? WHERE user_id=? AND account_id=?",
                                                (new_price, uid, aid),
                                            )
                                            conn.commit()
                                except Exception:
                                    pass
                last_prices = current_prices
            except Exception:
                pass

    threading.Thread(target=feature_monitor, name="premium-feature-monitor-v3", daemon=True).start()
