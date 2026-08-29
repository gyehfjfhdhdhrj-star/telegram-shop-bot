"""
MLBB MARKET - PREMIUM FEATURES ADDON
-------------------------------------
This file is intentionally separate from:
    main.py
    supabase_launcher.py

It does not replace either file. Call:
    install(original_main_module)

The addon adds:
1. ⚡ အမြန်ဝယ်
2. 🔥 Flash Deal
3. 🔔 ဈေးကျရင် အသိပေး
4. ✅ Admin စစ်ဆေးပြီး (Verified)
5. 👤 ကျွန်ုပ်၏အကောင့်
6. 🆕 အသစ်တင်ထားတဲ့အကောင့်များ
7. 🔎 အဆင့်မြင့်ရှာဖွေမယ်
8. 🔔 အသစ်တင်အကောင့် အသိပေးချက်
9. ❤️ သိမ်းထားတဲ့အကောင့်များ

Design rule:
- မူရင်း main.py ကို မပြင်ဘူး။
- မူရင်း menu/flow တွေကို မဖျက်ဘူး။
- Feature data ကို မူရင်း SQLite DB ထဲက သီးခြား tables နဲ့သာ သိမ်းတယ်။
- Message cleanup / delete မလုပ်ဘူး။
"""

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import threading
import time


def install(original):
    """
    Register premium features against the already-loaded original main module.
    `original` is the imported main.py module.
    """
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    bot = original.bot
    db_lock = original.db_lock
    db_connect = original.db_connect
    closing = original.closing
    ADMIN_ID = original.ADMIN_ID

    FEATURE_MORE = "premium_more"
    MY_ACCOUNT = "premium_my_account"

    # ------------------------------------------------------------------
    # DB: only add new tables/column; never drop/reset existing data.
    # ------------------------------------------------------------------
    def init_feature_db():
        with db_lock:
            with closing(db_connect()) as conn:
                cols = {r["name"] for r in conn.execute(
                    "PRAGMA table_info(accounts)"
                ).fetchall()}

                if "is_verified" not in cols:
                    conn.execute(
                        "ALTER TABLE accounts "
                        "ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
                    )

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS favorites (
                        user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, account_id)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_settings (
                        user_id INTEGER PRIMARY KEY,
                        new_account_alert INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS price_alerts (
                        user_id INTEGER NOT NULL,
                        account_id INTEGER NOT NULL,
                        last_price INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, account_id)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS flash_deals (
                        account_id INTEGER PRIMARY KEY,
                        deal_price INTEGER NOT NULL,
                        ends_at TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_flash_deals_ends
                    ON flash_deals(ends_at)
                """)

                conn.commit()

    init_feature_db()

    def rows(sql, params=()):
        with db_lock:
            with closing(db_connect()) as conn:
                return conn.execute(sql, params).fetchall()

    def account_obj(account_id):
        try:
            return original.get_account_by_text_id(
                original.make_account_id(int(account_id))
            )
        except Exception:
            return None

    def flash_for(account_id):
        found = rows(
            "SELECT deal_price, ends_at FROM flash_deals WHERE account_id=?",
            (int(account_id),),
        )
        if not found:
            return None

        try:
            ends = datetime.fromisoformat(
                str(found[0]["ends_at"]).replace("Z", "+00:00")
            )
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)

            if ends <= datetime.now(timezone.utc):
                with db_lock:
                    with closing(db_connect()) as conn:
                        conn.execute(
                            "DELETE FROM flash_deals WHERE account_id=?",
                            (int(account_id),),
                        )
                        conn.commit()
                return None

            return int(found[0]["deal_price"]), ends
        except Exception:
            return None

    def add_favorite(user_id, account_id):
        with db_lock:
            with closing(db_connect()) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM favorites WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()

                if exists:
                    conn.execute(
                        "DELETE FROM favorites WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    added = False
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO favorites(user_id, account_id) "
                        "VALUES(?, ?)",
                        (int(user_id), int(account_id)),
                    )
                    added = True

                conn.commit()
                return added

    def favorite_ids(user_id):
        result = rows(
            "SELECT account_id FROM favorites "
            "WHERE user_id=? ORDER BY created_at DESC",
            (int(user_id),),
        )
        return [int(r["account_id"]) for r in result]

    def new_alert_enabled(user_id):
        result = rows(
            "SELECT new_account_alert FROM feature_settings WHERE user_id=?",
            (int(user_id),),
        )
        return bool(result and int(result[0]["new_account_alert"] or 0))

    def set_new_alert(user_id, enabled):
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute("""
                    INSERT INTO feature_settings(user_id, new_account_alert)
                    VALUES(?, ?)
                    ON CONFLICT(user_id)
                    DO UPDATE SET new_account_alert=excluded.new_account_alert
                """, (int(user_id), 1 if enabled else 0))
                conn.commit()

    def set_price_alert(user_id, account_id):
        acc = account_obj(account_id)
        if not acc:
            return None

        current = int(acc.get("effective_price") or acc.get("price") or 0)

        with db_lock:
            with closing(db_connect()) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM price_alerts WHERE user_id=? AND account_id=?",
                    (int(user_id), int(account_id)),
                ).fetchone()

                if exists:
                    conn.execute(
                        "DELETE FROM price_alerts "
                        "WHERE user_id=? AND account_id=?",
                        (int(user_id), int(account_id)),
                    )
                    enabled = False
                else:
                    conn.execute("""
                        INSERT OR REPLACE INTO price_alerts(
                            user_id, account_id, last_price
                        ) VALUES(?, ?, ?)
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

    def verified(account_id):
        result = rows(
            "SELECT is_verified FROM accounts WHERE id=?",
            (int(account_id),),
        )
        return bool(result and int(result[0]["is_verified"] or 0))

    def set_flash(account_id, deal_price, minutes):
        ends = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        with db_lock:
            with closing(db_connect()) as conn:
                conn.execute("""
                    INSERT INTO flash_deals(account_id, deal_price, ends_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(account_id)
                    DO UPDATE SET
                        deal_price=excluded.deal_price,
                        ends_at=excluded.ends_at
                """, (int(account_id), int(deal_price), ends.isoformat()))
                conn.commit()

    # ------------------------------------------------------------------
    # Display wrappers. Existing function output is preserved and only
    # feature lines are added.
    # ------------------------------------------------------------------
    if not hasattr(original, "_premium_original_row_to_account"):
        original._premium_original_row_to_account = original.row_to_account

    if not hasattr(original, "_premium_original_format_account"):
        original._premium_original_format_account = original.format_account

    def wrapped_row_to_account(row):
        acc = original._premium_original_row_to_account(row)
        try:
            keys = row.keys()
            acc["is_verified"] = (
                int(row["is_verified"] or 0)
                if "is_verified" in keys else 0
            )
        except Exception:
            acc["is_verified"] = 0
        return acc

    def wrapped_format_account(acc):
        base = original._premium_original_format_account(acc)
        lines = base.split("\n")

        # Do not duplicate lines if this function is called more than once.
        if acc.get("skins"):
            if not any("Skin အတိုချုပ်" in x for x in lines):
                insert_at = min(3, len(lines))
                short_skins = str(acc.get("skins", "")).replace("\n", " ").strip()
                if len(short_skins) > 100:
                    short_skins = short_skins[:97] + "..."
                lines.insert(
                    insert_at,
                    f"🎨 <b>Skin အတိုချုပ် — {short_skins}</b>",
                )

        if acc.get("is_verified"):
            if not any("ADMIN စစ်ဆေးပြီး" in x for x in lines):
                lines.insert(
                    min(4, len(lines)),
                    "✅ <b>ADMIN စစ်ဆေးပြီး</b>",
                )

        flash = flash_for(acc.get("db_id", 0))
        if flash:
            deal_price, _ = flash
            if not any("FLASH DEAL" in x for x in lines):
                lines.append(
                    f"🔥 <b>FLASH DEAL — {deal_price:,} MMK</b>"
                )

        return "\n".join(lines)

    original.row_to_account = wrapped_row_to_account
    original.format_account = wrapped_format_account

    # ------------------------------------------------------------------
    # Menus: wrap, don't replace the original main/admin menus.
    # ------------------------------------------------------------------
    if not hasattr(original, "_premium_original_main_menu"):
        original._premium_original_main_menu = original.main_menu

    if not hasattr(original, "_premium_original_admin_keyboard"):
        original._premium_original_admin_keyboard = original.admin_keyboard

    def premium_main_menu(user_id):
        markup = original._premium_original_main_menu(user_id)

        # Keep existing buttons exactly as they are.
        markup.add(
            InlineKeyboardButton(
                "👤 ကျွန်ုပ်၏အကောင့်",
                callback_data=MY_ACCOUNT,
            ),
            InlineKeyboardButton(
                "✨ အခြားအသုံးဝင်တဲ့ Features",
                callback_data=FEATURE_MORE,
            ),
        )
        return markup

    def premium_admin_keyboard():
        markup = original._premium_original_admin_keyboard()
        markup.add(
            InlineKeyboardButton(
                "✨ Feature စီမံမယ်",
                callback_data="premium_admin_tools",
            )
        )
        return markup

    original.main_menu = premium_main_menu
    original.admin_keyboard = premium_admin_keyboard

    def feature_more_markup():
        m = InlineKeyboardMarkup(row_width=2)
        m.add(
            InlineKeyboardButton("❤️ သိမ်းထားတဲ့အကောင့်များ", callback_data="premium_favorites"),
            InlineKeyboardButton("🆕 အသစ်တင်ထားတဲ့အကောင့်များ", callback_data="premium_new_accounts"),
            InlineKeyboardButton("🔎 အဆင့်မြင့်ရှာဖွေမယ်", callback_data="premium_advanced_search"),
            InlineKeyboardButton("🔥 Flash Deal အကောင့်များ", callback_data="premium_flash_deals"),
            InlineKeyboardButton("✅ စစ်ဆေးပြီးအကောင့်များ", callback_data="premium_verified"),
            InlineKeyboardButton("🔔 အသစ်တင်အသိပေးချက်", callback_data="premium_new_alert"),
            InlineKeyboardButton("💡 Tips", callback_data="tips_menu"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        return m

    def feature_account_markup(acc, kind, index, total):
        if kind == "favorites":
            prev_cb, next_cb = "premium_fav_prev", "premium_fav_next"
        elif kind == "new":
            prev_cb, next_cb = "premium_new_prev", "premium_new_next"
        elif kind == "verified":
            prev_cb, next_cb = "premium_ver_prev", "premium_ver_next"
        else:
            prev_cb, next_cb = "premium_search_prev", "premium_search_next"

        m = InlineKeyboardMarkup(row_width=2)
        m.row(
            InlineKeyboardButton("⬅️ အရင်အကောင့်", callback_data=prev_cb),
            InlineKeyboardButton("နောက်အကောင့် ➡️", callback_data=next_cb),
        )
        m.row(
            InlineKeyboardButton(
                "⚡ အမြန်ဝယ်မယ်",
                callback_data=f"premium_fast_buy_{acc['id']}",
            ),
            InlineKeyboardButton(
                "❤️ သိမ်းထားမယ်",
                callback_data=f"premium_fav_toggle_{acc['db_id']}",
            ),
        )
        m.row(
            InlineKeyboardButton(
                "🔔 ဈေးကျရင် အသိပေးမယ်",
                callback_data=f"premium_price_alert_{acc['db_id']}",
            ),
        )
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        return m

    def send_feature_account(chat_id, acc, kind, index, total):
        if not acc:
            bot.send_message(
                chat_id,
                "❌ ဒီအကောင့် မရှိတော့ပါ။",
                reply_markup=original.back_button(),
            )
            return

        # Use the original photo sender so existing Supabase-photo handling
        # and existing account photo behavior remain untouched.
        try:
            original.send_account_photos(chat_id, acc, include_menu=False)
        except Exception:
            # Fallback to text if a photo cannot be sent.
            bot.send_message(chat_id, wrapped_format_account(acc), parse_mode="HTML")

        bot.send_message(
            chat_id,
            f"🎯 <b>{index + 1} / {total}</b>\n\n{wrapped_format_account(acc)}",
            parse_mode="HTML",
            reply_markup=feature_account_markup(acc, kind, index, total),
        )

    def ids_from_favorites(user_id):
        return [
            original.make_account_id(x)
            for x in favorite_ids(user_id)
            if account_obj(x)
        ]

    def ids_from_new_accounts():
        result = rows(
            "SELECT id FROM accounts "
            "WHERE status='available' ORDER BY id ASC"
        )
        return [original.make_account_id(int(r["id"])) for r in result]

    def ids_from_verified():
        result = rows(
            "SELECT id FROM accounts "
            "WHERE status='available' AND is_verified=1 "
            "ORDER BY id ASC"
        )
        return [original.make_account_id(int(r["id"])) for r in result]

    def set_nav_state(user_id, kind, ids, index):
        original.set_state(
            user_id,
            {
                "flow": f"premium_{kind}",
                "premium_ids": ids,
                "premium_index": int(index),
                "premium_kind": kind,
            },
        )

    def show_nav_from_state(call, direction):
        state = original.get_state(call.from_user.id)
        ids = state.get("premium_ids", [])
        if not ids:
            bot.send_message(
                call.message.chat.id,
                "❌ ကြည့်ရန်အကောင့် မရှိသေးပါ။",
                reply_markup=feature_more_markup(),
            )
            return

        idx = int(state.get("premium_index", 0))
        idx += int(direction)
        idx %= len(ids)
        state["premium_index"] = idx
        original.set_state(call.from_user.id, state)

        acc = original.get_account_by_text_id(ids[idx])
        send_feature_account(
            call.message.chat.id,
            acc,
            state.get("premium_kind", "search"),
            idx,
            len(ids),
        )

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == FEATURE_MORE)
    def premium_more(call):
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "✨ <b>အသုံးဝင်တဲ့ Features</b>\n\n"
            "လိုချင်တဲ့ feature ကို ရွေးပါ။",
            parse_mode="HTML",
            reply_markup=feature_more_markup(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == MY_ACCOUNT)
    def premium_my_account(call):
        bot.answer_callback_query(call.id)
        uid = call.from_user.id
        favs = len(favorite_ids(uid))
        alert = "ဖွင့်ထားပါတယ် ✅" if new_alert_enabled(uid) else "ပိတ်ထားပါတယ် ❌"

        text = (
            "👤 <b>ကျွန်ုပ်၏အကောင့်</b>\n\n"
            f"🆔 User ID — <code>{uid}</code>\n"
            f"❤️ သိမ်းထားတဲ့အကောင့် — <b>{favs}</b> ခု\n"
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

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_favorites")
    def premium_favorites(call):
        bot.answer_callback_query(call.id)
        ids = ids_from_favorites(call.from_user.id)
        if not ids:
            bot.send_message(
                call.message.chat.id,
                "❤️ <b>သိမ်းထားတဲ့အကောင့် မရှိသေးပါ။</b>",
                parse_mode="HTML",
                reply_markup=feature_more_markup(),
            )
            return
        set_nav_state(call.from_user.id, "favorites", ids, 0)
        send_feature_account(
            call.message.chat.id,
            original.get_account_by_text_id(ids[0]),
            "favorites",
            0,
            len(ids),
        )

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_fav_prev", "premium_fav_next"))
    def premium_fav_nav(call):
        bot.answer_callback_query(call.id)
        show_nav_from_state(call, -1 if call.data.endswith("prev") else 1)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_fav_toggle_"))
    def premium_fav_toggle(call):
        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_fav_toggle_", "", 1))
        acc = account_obj(aid)
        if not acc:
            bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=feature_more_markup())
            return

        added = add_favorite(call.from_user.id, aid)
        bot.send_message(
            call.message.chat.id,
            (
                f"❤️ <b>{acc['id']}</b> ကို သိမ်းထားလိုက်ပါပြီ။"
                if added
                else f"💔 <b>{acc['id']}</b> ကို သိမ်းထားတာ ဖြုတ်လိုက်ပါပြီ။"
            ),
            parse_mode="HTML",
            reply_markup=feature_more_markup(),
        )

    # ------------------------------------------------------------------
    # New accounts
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_new_accounts")
    def premium_new_accounts(call):
        bot.answer_callback_query(call.id)
        ids = ids_from_new_accounts()
        if not ids:
            bot.send_message(
                call.message.chat.id,
                "🆕 <b>အသစ်တင်ထားတဲ့အကောင့် မရှိသေးပါ။</b>",
                parse_mode="HTML",
                reply_markup=feature_more_markup(),
            )
            return
        set_nav_state(call.from_user.id, "new", ids, 0)
        send_feature_account(
            call.message.chat.id,
            original.get_account_by_text_id(ids[0]),
            "new",
            0,
            len(ids),
        )

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_new_prev", "premium_new_next"))
    def premium_new_nav(call):
        bot.answer_callback_query(call.id)
        show_nav_from_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------------
    # Verified
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_verified")
    def premium_verified(call):
        bot.answer_callback_query(call.id)
        ids = ids_from_verified()
        if not ids:
            bot.send_message(
                call.message.chat.id,
                "✅ <b>စစ်ဆေးပြီးအကောင့် မရှိသေးပါ။</b>",
                parse_mode="HTML",
                reply_markup=feature_more_markup(),
            )
            return
        set_nav_state(call.from_user.id, "verified", ids, 0)
        send_feature_account(
            call.message.chat.id,
            original.get_account_by_text_id(ids[0]),
            "verified",
            0,
            len(ids),
        )

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_ver_prev", "premium_ver_next"))
    def premium_ver_nav(call):
        bot.answer_callback_query(call.id)
        show_nav_from_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------------
    # New-account alerts
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_new_alert")
    def premium_new_alert(call):
        bot.answer_callback_query(call.id)
        enabled = not new_alert_enabled(call.from_user.id)
        set_new_alert(call.from_user.id, enabled)
        bot.send_message(
            call.message.chat.id,
            (
                "🔔 <b>အသစ်တင်အကောင့် အသိပေးချက် ဖွင့်ပြီးပါပြီ။</b>"
                if enabled
                else "🔕 <b>အသစ်တင်အကောင့် အသိပေးချက် ပိတ်ပြီးပါပြီ။</b>"
            ),
            parse_mode="HTML",
            reply_markup=feature_more_markup(),
        )

    # ------------------------------------------------------------------
    # Price alerts
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_price_alert_"))
    def premium_price_alert(call):
        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_price_alert_", "", 1))
        acc = account_obj(aid)
        enabled = set_price_alert(call.from_user.id, aid) if acc else None

        if enabled is None:
            bot.send_message(call.message.chat.id, "❌ Account မတွေ့ပါ။", reply_markup=feature_more_markup())
            return

        bot.send_message(
            call.message.chat.id,
            (
                f"🔔 <b>{acc['id']}</b> ဈေးကျရင် အသိပေးပါမယ်။"
                if enabled
                else f"🔕 <b>{acc['id']}</b> ရဲ့ ဈေးကျအသိပေးချက်ကို ပိတ်လိုက်ပါပြီ။"
            ),
            parse_mode="HTML",
            reply_markup=feature_more_markup(),
        )

    # ------------------------------------------------------------------
    # Fast buy
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_fast_buy_"))
    def premium_fast_buy(call):
        bot.answer_callback_query(call.id)
        aid = call.data.replace("premium_fast_buy_", "", 1)
        acc = original.get_account_by_text_id(aid)

        if not acc or acc.get("status") != "available":
            bot.send_message(
                call.message.chat.id,
                "❌ ဒီအကောင့် လက်ရှိ ဝယ်ယူလို့မရတော့ပါ။",
                reply_markup=feature_more_markup(),
            )
            return

        deal = flash_for(acc["db_id"])
        price = deal[0] if deal else int(acc.get("effective_price") or acc["price"])

        m = InlineKeyboardMarkup(row_width=1)
        if original.ADMIN_USERNAME:
            m.add(
                InlineKeyboardButton(
                    "👨‍💻 Admin ကို တိုက်ရိုက်ဆက်သွယ်မယ်",
                    url=f"https://t.me/{original.ADMIN_USERNAME}",
                )
            )
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))

        bot.send_message(
            call.message.chat.id,
            f"⚡ <b>အမြန်ဝယ်ယူမယ်</b>\n\n"
            f"{wrapped_format_account(acc)}\n\n"
            f"💰 <b>ဝယ်ဈေး — {price:,} MMK</b>\n\n"
            "ဝယ်ယူဖို့ Admin ကို တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။",
            parse_mode="HTML",
            reply_markup=m,
        )

    # ------------------------------------------------------------------
    # Advanced search
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_advanced_search")
    def premium_advanced_search_start(call):
        bot.answer_callback_query(call.id)
        original.set_state(call.from_user.id, {"flow": "premium_advanced_search"})
        msg = bot.send_message(
            call.message.chat.id,
            "🔎 <b>အဆင့်မြင့်ရှာဖွေမယ်</b>\n\n"
            "ဒီလိုပုံစံနဲ့ ရိုက်ပို့ပါ —\n"
            "<code>Skin | အနည်းဆုံးဈေး | အများဆုံးဈေး</code>\n\n"
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
            msg = bot.send_message(
                message.chat.id,
                "❌ Format မမှန်ပါ။\n"
                "<code>Collector | 100000 | 200000</code>",
                parse_mode="HTML",
                reply_markup=original.back_button(),
            )
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
            msg = bot.send_message(
                message.chat.id,
                "❌ ဈေးနှုန်း မမှန်ပါ။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(msg, premium_advanced_search_receive)
            return

        scored = []
        for acc in original.get_available_accounts():
            price = int(acc.get("effective_price") or acc["price"])
            if not (min_price <= price <= max_price):
                continue

            hay = " ".join(
                [str(acc.get("title", "")), str(acc.get("skins", ""))]
            ).lower()

            if skin:
                target = skin.lower()
                score = SequenceMatcher(None, target, hay).ratio() * 100
                for token in hay.replace(",", " ").split():
                    score = max(
                        score,
                        SequenceMatcher(None, target, token).ratio() * 100,
                    )
                if target in hay:
                    score += 35
                if score < 22:
                    continue
            else:
                score = 1

            scored.append((score, acc))

        scored.sort(
            key=lambda item: (
                -item[0],
                int(item[1].get("effective_price") or item[1]["price"]),
                int(item[1]["db_id"]),
            )
        )

        ids = [acc["id"] for _, acc in scored]
        if not ids:
            bot.send_message(
                message.chat.id,
                "❌ အနီးစပ်ဆုံး Account မတွေ့သေးပါ။",
                reply_markup=feature_more_markup(),
            )
            return

        original.set_state(
            message.from_user.id,
            {
                "flow": "premium_search",
                "premium_ids": ids,
                "premium_index": 0,
                "premium_kind": "search",
            },
        )

        send_feature_account(
            message.chat.id,
            original.get_account_by_text_id(ids[0]),
            "search",
            0,
            len(ids),
        )

    @bot.callback_query_handler(func=lambda c: c.data in ("premium_search_prev", "premium_search_next"))
    def premium_search_nav(call):
        bot.answer_callback_query(call.id)
        show_nav_from_state(call, -1 if call.data.endswith("prev") else 1)

    # ------------------------------------------------------------------
    # Flash deals
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_flash_deals")
    def premium_flash_deals(call):
        bot.answer_callback_query(call.id)

        active = []
        for r in rows(
            "SELECT account_id, deal_price, ends_at "
            "FROM flash_deals ORDER BY ends_at ASC"
        ):
            deal = flash_for(int(r["account_id"]))
            acc = account_obj(int(r["account_id"]))
            if deal and acc and acc.get("status") == "available":
                active.append((acc, deal[0], deal[1]))

        if not active:
            bot.send_message(
                call.message.chat.id,
                "🔥 လက်ရှိ Flash Deal မရှိသေးပါ။",
                reply_markup=feature_more_markup(),
            )
            return

        m = InlineKeyboardMarkup(row_width=1)
        lines = ["🔥 <b>FLASH DEAL အကောင့်များ</b>\n"]

        for acc, price, ends in active:
            remain = max(0, int((ends - datetime.now(timezone.utc)).total_seconds()))
            minutes = remain // 60
            seconds = remain % 60
            lines.append(
                f"🆔 <b>{acc['id']}</b> — "
                f"🔥 <b>{price:,} MMK</b> — "
                f"⏰ {minutes:02d}:{seconds:02d}"
            )
            m.add(
                InlineKeyboardButton(
                    f"⚡ {acc['id']} အမြန်ဝယ်မယ်",
                    callback_data=f"premium_flash_buy_{acc['id']}",
                )
            )

        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        bot.send_message(
            call.message.chat.id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=m,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_flash_buy_"))
    def premium_flash_buy(call):
        bot.answer_callback_query(call.id)
        aid = call.data.replace("premium_flash_buy_", "", 1)
        acc = original.get_account_by_text_id(aid)
        deal = flash_for(acc["db_id"]) if acc else None

        if not acc or not deal:
            bot.send_message(
                call.message.chat.id,
                "❌ Flash Deal သက်တမ်းကုန်သွားပါပြီ။",
                reply_markup=feature_more_markup(),
            )
            return

        price = deal[0]
        m = InlineKeyboardMarkup(row_width=1)
        if original.ADMIN_USERNAME:
            m.add(
                InlineKeyboardButton(
                    "👨‍💻 Admin ကို ဆက်သွယ်မယ်",
                    url=f"https://t.me/{original.ADMIN_USERNAME}",
                )
            )
        m.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))

        bot.send_message(
            call.message.chat.id,
            f"🔥 <b>FLASH DEAL</b>\n\n"
            f"{wrapped_format_account(acc)}\n\n"
            f"💰 <b>{price:,} MMK</b>\n\n"
            "⚡ ဒီဈေးနဲ့ ဝယ်ယူဖို့ Admin ကို ဆက်သွယ်ပါ။",
            parse_mode="HTML",
            reply_markup=m,
        )

    # ------------------------------------------------------------------
    # Admin feature tools
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_tools")
    def premium_admin_tools(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(
                call.id,
                "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)
        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton(
                "🔥 Flash Deal စီမံမယ်",
                callback_data="premium_admin_flash_list",
            ),
            InlineKeyboardButton(
                "✅ Verified စီမံမယ်",
                callback_data="premium_admin_verified_list",
            ),
            InlineKeyboardButton(
                "🔔 အသိပေးချက် အသုံးပြုသူများ",
                callback_data="premium_admin_alert_stats",
            ),
            InlineKeyboardButton(
                "🏠 Admin Menu",
                callback_data="admin_home",
            ),
        )
        bot.send_message(
            ADMIN_ID,
            "✨ <b>Feature စီမံမယ်</b>",
            parse_mode="HTML",
            reply_markup=m,
        )

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_flash_list")
    def premium_admin_flash_list(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        m = InlineKeyboardMarkup(row_width=1)
        for acc in original.get_admin_accounts(status="available")[:50]:
            m.add(
                InlineKeyboardButton(
                    f"🔥 {acc['id']} — {acc['effective_price']:,} MMK",
                    callback_data=f"premium_admin_flash_{acc['id']}",
                )
            )
        m.add(
            InlineKeyboardButton(
                "🔙 Feature စီမံမယ်",
                callback_data="premium_admin_tools",
            )
        )
        bot.send_message(
            ADMIN_ID,
            "🔥 Flash Deal တင်မယ့် Account ကို ရွေးပါ။",
            reply_markup=m,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_admin_flash_"))
    def premium_admin_flash_start(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        aid = call.data.replace("premium_admin_flash_", "", 1)
        acc = original.get_account_by_text_id(aid)
        if not acc:
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=original.admin_keyboard())
            return

        original.set_state(
            ADMIN_ID,
            {
                "flow": "premium_admin_flash",
                "premium_flash_account_id": aid,
            },
        )

        msg = bot.send_message(
            ADMIN_ID,
            f"🔥 <b>{aid}</b> Flash Deal\n\n"
            "ဒီပုံစံနဲ့ ရိုက်ပါ — <code>Deal ဈေး | မိနစ်</code>\n"
            "ဥပမာ — <code>90000 | 60</code>",
            parse_mode="HTML",
            reply_markup=original.back_button(),
        )
        bot.register_next_step_handler(msg, premium_admin_flash_receive)

    def premium_admin_flash_receive(message):
        if message.from_user.id != ADMIN_ID:
            return

        state = original.get_state(ADMIN_ID)
        if state.get("flow") != "premium_admin_flash":
            return

        parts = [x.strip() for x in (message.text or "").split("|", 1)]
        if len(parts) != 2:
            msg = bot.send_message(
                ADMIN_ID,
                "❌ Format မမှန်ပါ။ <code>90000 | 60</code>",
                parse_mode="HTML",
            )
            bot.register_next_step_handler(msg, premium_admin_flash_receive)
            return

        try:
            deal_price = int(parts[0].replace(",", "").replace(" ", ""))
            minutes = int(parts[1])
            if deal_price <= 0 or minutes <= 0:
                raise ValueError
        except Exception:
            msg = bot.send_message(
                ADMIN_ID,
                "❌ ဈေး/အချိန် မမှန်ပါ။",
                reply_markup=original.back_button(),
            )
            bot.register_next_step_handler(msg, premium_admin_flash_receive)
            return

        aid = state.get("premium_flash_account_id")
        acc = original.get_account_by_text_id(aid)
        if not acc:
            original.clear_state(ADMIN_ID)
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=original.admin_keyboard())
            return

        set_flash(acc["db_id"], deal_price, minutes)
        original.clear_state(ADMIN_ID)

        bot.send_message(
            ADMIN_ID,
            f"✅ <b>{aid}</b> Flash Deal တင်ပြီးပါပြီ။\n\n"
            f"🔥 Deal ဈေး — {deal_price:,} MMK\n"
            f"⏰ သက်တမ်း — {minutes} မိနစ်",
            parse_mode="HTML",
            reply_markup=original.admin_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_verified_list")
    def premium_admin_verified_list(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        m = InlineKeyboardMarkup(row_width=1)
        for acc in original.get_admin_accounts()[:50]:
            icon = "✅" if verified(acc["db_id"]) else "⬜"
            m.add(
                InlineKeyboardButton(
                    f"{icon} {acc['id']}",
                    callback_data=f"premium_admin_verify_{acc['db_id']}",
                )
            )
        m.add(
            InlineKeyboardButton(
                "🔙 Feature စီမံမယ်",
                callback_data="premium_admin_tools",
            )
        )
        bot.send_message(
            ADMIN_ID,
            "✅ Verified လုပ်/ဖြုတ်မယ့် Account ကို ရွေးပါ။",
            reply_markup=m,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("premium_admin_verify_"))
    def premium_admin_verify(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        aid = int(call.data.replace("premium_admin_verify_", "", 1))
        acc = account_obj(aid)
        if not acc:
            bot.send_message(ADMIN_ID, "❌ Account မတွေ့ပါ။", reply_markup=original.admin_keyboard())
            return

        enabled = not verified(aid)
        set_verified(aid, enabled)

        bot.send_message(
            ADMIN_ID,
            (
                f"✅ <b>{acc['id']}</b> ကို Verified လုပ်ပြီးပါပြီ။"
                if enabled
                else f"❌ <b>{acc['id']}</b> Verified ဖြုတ်ပြီးပါပြီ။"
            ),
            parse_mode="HTML",
            reply_markup=original.admin_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "premium_admin_alert_stats")
    def premium_admin_alert_stats(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        new_alert_users = rows(
            "SELECT COUNT(*) AS n FROM feature_settings "
            "WHERE new_account_alert=1"
        )[0]["n"]
        price_alert_users = rows(
            "SELECT COUNT(DISTINCT user_id) AS n FROM price_alerts"
        )[0]["n"]

        bot.send_message(
            ADMIN_ID,
            "🔔 <b>အသိပေးချက် အချက်အလက်</b>\n\n"
            f"🆕 အသစ်တင်အသိပေးချက် ဖွင့်ထားသူ — <b>{new_alert_users}</b> ယောက်\n"
            f"💸 ဈေးကျအသိပေးချက် အသုံးပြုသူ — <b>{price_alert_users}</b> ယောက်",
            parse_mode="HTML",
            reply_markup=original.admin_keyboard(),
        )

    # ------------------------------------------------------------------
    # Background monitor: new-account notifications + price-drop alerts.
    # No message deletion. No changes to existing account flow.
    # ------------------------------------------------------------------
    stop_event = threading.Event()

    # Baselines: existing records are not treated as new after startup.
    current = rows("SELECT COALESCE(MAX(id), 0) AS max_id FROM accounts")
    last_account_id = int(current[0]["max_id"] or 0)

    price_rows = rows(
        "SELECT id, COALESCE(sale_price, price) AS p FROM accounts"
    )
    last_prices = {
        int(r["id"]): int(r["p"] or 0)
        for r in price_rows
    }

    def feature_monitor():
        nonlocal last_account_id, last_prices

        while not stop_event.wait(10):
            try:
                available = rows("""
                    SELECT id, COALESCE(sale_price, price) AS p
                    FROM accounts
                    WHERE status='available'
                    ORDER BY id ASC
                """)

                max_id = max((int(r["id"]) for r in available), default=last_account_id)

                if max_id > last_account_id:
                    new_rows = [
                        r for r in available if int(r["id"]) > last_account_id
                    ]

                    alert_users = rows(
                        "SELECT user_id FROM feature_settings "
                        "WHERE new_account_alert=1"
                    )

                    for r in new_rows:
                        acc = account_obj(int(r["id"]))
                        if not acc:
                            continue

                        for user_row in alert_users:
                            uid = int(user_row["user_id"])
                            try:
                                m = InlineKeyboardMarkup(row_width=1)
                                m.add(
                                    InlineKeyboardButton(
                                        "⚡ အမြန်ဝယ်မယ်",
                                        callback_data=f"premium_fast_buy_{acc['id']}",
                                    )
                                )
                                bot.send_message(
                                    uid,
                                    "🆕 <b>Account အသစ်တင်ထားပါတယ်!</b>\n\n"
                                    + wrapped_format_account(acc),
                                    parse_mode="HTML",
                                    reply_markup=m,
                                )
                            except Exception:
                                pass

                    last_account_id = max_id

                current_prices = {
                    int(r["id"]): int(r["p"] or 0)
                    for r in available
                }

                for aid, new_price in current_prices.items():
                    old_price = last_prices.get(aid, new_price)
                    if new_price < old_price:
                        alert_rows = rows(
                            "SELECT user_id, last_price FROM price_alerts "
                            "WHERE account_id=?",
                            (aid,),
                        )
                        acc = account_obj(aid)
                        if not acc:
                            continue

                        for alert_row in alert_rows:
                            uid = int(alert_row["user_id"])
                            old_alert_price = int(alert_row["last_price"] or 0)

                            if new_price < old_alert_price:
                                try:
                                    m = InlineKeyboardMarkup(row_width=1)
                                    m.add(
                                        InlineKeyboardButton(
                                            "⚡ အမြန်ဝယ်မယ်",
                                            callback_data=f"premium_fast_buy_{acc['id']}",
                                        )
                                    )
                                    bot.send_message(
                                        uid,
                                        "🔔 <b>ဈေးကျသွားပါပြီ!</b>\n\n"
                                        + wrapped_format_account(acc)
                                        + f"\n\n💸 ယခုဈေး — <b>{new_price:,} MMK</b>",
                                        parse_mode="HTML",
                                        reply_markup=m,
                                    )

                                    with db_lock:
                                        with closing(db_connect()) as conn:
                                            conn.execute(
                                                "UPDATE price_alerts "
                                                "SET last_price=? "
                                                "WHERE user_id=? AND account_id=?",
                                                (new_price, uid, aid),
                                            )
                                            conn.commit()
                                except Exception:
                                    pass

                last_prices = current_prices
            except Exception:
                # Background notifications must never take down the bot.
                pass

    threading.Thread(
        target=feature_monitor,
        name="premium-feature-monitor",
        daemon=True,
    ).start()

    # Ensure startup migrations are harmless and existing records stay intact.
    return {
        "feature_more_callback": FEATURE_MORE,
        "my_account_callback": MY_ACCOUNT,
        "tables_ready": True,
    }
