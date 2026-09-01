"""
MLBB MARKET - ADVANCED MARKETPLACE ADDON v1
===========================================

Separate addon for the existing bot.  It does not edit main.py,
premium_features_v17.py, supabase_launcher.py, or the Gmail modules.

Adds:
1) Admin Pending Queue
2) Guided Search and a compact account card
3) My Orders / My Sales
4) Admin Dashboard
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import html
import logging

from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


_INSTALLED = False


def install(original):
    """Install the advanced addon on an already-loaded main.py module."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    bot = original.bot
    admin_id = int(original.ADMIN_ID)
    db_lock = original.db_lock
    db_connect = original.db_connect

    def esc(value):
        return html.escape(str(value or ""))

    def rows(sql, params=()):
        with db_lock:
            with closing(db_connect()) as conn:
                return conn.execute(sql, params).fetchall()

    def row(sql, params=()):
        result = rows(sql, params)
        return result[0] if result else None

    def scalar(sql, params=(), default=0):
        result = row(sql, params)
        if result is None:
            return default
        try:
            return result[0]
        except Exception:
            return default

    def safe_rows(sql, params=()):
        try:
            return rows(sql, params)
        except Exception:
            logging.exception("ADVANCED_QUERY_FAILED sql=%s", sql[:120])
            return []

    def safe_answer(call, text=None, alert=False):
        try:
            bot.answer_callback_query(
                call.id,
                text=text,
                show_alert=bool(alert),
            )
        except Exception:
            pass

    def is_admin(call):
        if int(call.from_user.id) == admin_id:
            return True
        safe_answer(call, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", True)
        return False

    def log_action(user, action, details=""):
        try:
            original.log_user_activity(user, action, details)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Shared menus
    # ------------------------------------------------------------------
    def reply_keyboard():
        kb = ReplyKeyboardMarkup(
            resize_keyboard=True,
            one_time_keyboard=False,
            row_width=2,
        )
        kb.row(
            KeyboardButton("🛒 အကောင့်ဝယ်မယ်"),
            KeyboardButton("👀 အကောင့်ကြည့်မယ်"),
        )
        kb.row(
            KeyboardButton("💰 အကောင့်ရောင်းမယ်"),
            KeyboardButton("💸 လျော့စျေးအကောင့်များ"),
        )
        return kb

    def home_menu(user_id):
        menu = InlineKeyboardMarkup(row_width=2)
        menu.row(
            InlineKeyboardButton(
                "🔎 Guided Search",
                callback_data="adv_search",
            ),
            InlineKeyboardButton(
                "📦 ကျွန်ုပ်၏အော်ဒါများ",
                callback_data="adv_my_hub",
            ),
        )
        menu.row(
            InlineKeyboardButton(
                "❤️ သိမ်းထားတာ",
                callback_data="premium_favorites",
            ),
            InlineKeyboardButton(
                "🆕 အသစ်တင်ထားတာ",
                callback_data="premium_new_accounts",
            ),
        )
        menu.row(
            InlineKeyboardButton(
                "💸 လျော့စျေးအကောင့်များ",
                callback_data="premium_discount_accounts",
            ),
            InlineKeyboardButton(
                "🔥 Special Deals",
                callback_data="premium_special_deals",
            ),
        )
        if int(user_id) == admin_id:
            menu.row(
                InlineKeyboardButton(
                    "🗂️ Pending Queue",
                    callback_data="adv_admin_queue",
                ),
                InlineKeyboardButton(
                    "📊 Dashboard",
                    callback_data="adv_admin_dashboard",
                ),
            )
            menu.add(
                InlineKeyboardButton(
                    "👑 Admin Panel",
                    callback_data="admin_home",
                )
            )
        return menu

    def send_home(chat_id, user_id, with_reply_keyboard=False):
        if with_reply_keyboard:
            bot.send_message(
                chat_id,
                "🏠 <b>Aung Gyi GameShop</b>\n"
                "အောက်က Menu ကနေ လိုတာကို ရွေးပါ။",
                parse_mode="HTML",
                reply_markup=reply_keyboard(),
            )
            bot.send_message(
                chat_id,
                "✨ <b>Marketplace Services</b>",
                parse_mode="HTML",
                reply_markup=home_menu(user_id),
            )
            return
        bot.send_message(
            chat_id,
            "🏠 <b>Aung Gyi GameShop</b>",
            parse_mode="HTML",
            reply_markup=home_menu(user_id),
        )

    # Preserve the existing Admin menu and append the new tools.
    if not hasattr(original, "_advanced_v1_previous_admin_keyboard"):
        original._advanced_v1_previous_admin_keyboard = original.admin_keyboard

        def advanced_admin_keyboard():
            menu = original._advanced_v1_previous_admin_keyboard()
            existing = {
                getattr(button, "callback_data", None)
                for keyboard_row in getattr(menu, "keyboard", [])
                for button in keyboard_row
            }
            if "adv_admin_queue" not in existing:
                menu.row(
                    InlineKeyboardButton(
                        "🗂️ Pending Queue",
                        callback_data="adv_admin_queue",
                    ),
                    InlineKeyboardButton(
                        "📊 Dashboard",
                        callback_data="adv_admin_dashboard",
                    ),
                )
            return menu

        original.admin_keyboard = advanced_admin_keyboard

    # ------------------------------------------------------------------
    # Guided Search
    # ------------------------------------------------------------------
    default_filters = {
        "min_price": 0,
        "max_price": 0,
        "verified": 0,
        "discounted": 0,
        "sort": "newest",
        "keyword": "",
    }

    budget_presets = {
        "any": (0, 0, "အားလုံး"),
        "u50": (0, 50000, "50,000 အောက်"),
        "u100": (0, 100000, "100,000 အောက်"),
        "100to200": (100000, 200000, "100,000–200,000"),
        "200to300": (200000, 300000, "200,000–300,000"),
        "300plus": (300000, 0, "300,000 အထက်"),
    }

    sort_labels = {
        "newest": "အသစ်ဆုံးအရင်",
        "low": "ဈေးအနိမ့်ဆုံးအရင်",
        "high": "ဈေးအမြင့်ဆုံးအရင်",
    }

    def normalize_filters(value=None):
        result = dict(default_filters)
        if isinstance(value, dict):
            for key in result:
                if key in value:
                    result[key] = value[key]
        result["min_price"] = max(0, int(result["min_price"] or 0))
        result["max_price"] = max(0, int(result["max_price"] or 0))
        result["verified"] = 1 if result["verified"] else 0
        result["discounted"] = 1 if result["discounted"] else 0
        if result["sort"] not in sort_labels:
            result["sort"] = "newest"
        result["keyword"] = str(result["keyword"] or "").strip()[:80]
        return result

    def current_filters(user_id):
        state = original.get_state(int(user_id)) or {}
        return normalize_filters(state.get("adv_filters"))

    def save_search_state(user_id, filters, flow="adv_search", **extra):
        state = {
            "flow": flow,
            "adv_filters": normalize_filters(filters),
        }
        state.update(extra)
        original.set_state(int(user_id), state)

    def budget_text(filters):
        minimum = int(filters["min_price"] or 0)
        maximum = int(filters["max_price"] or 0)
        if minimum and maximum:
            return f"{minimum:,}–{maximum:,} MMK"
        if maximum:
            return f"{maximum:,} MMK အောက်"
        if minimum:
            return f"{minimum:,} MMK အထက်"
        return "အားလုံး"

    def search_summary(filters):
        keyword = esc(filters["keyword"] or "မရွေးရသေး")
        verified = "လိုအပ် ✅" if filters["verified"] else "မကန့်သတ်"
        discounted = "လျော့စျေးသာ ✅" if filters["discounted"] else "မကန့်သတ်"
        return (
            "🔎 <b>Guided Account Search</b>\n\n"
            f"💰 Budget — <b>{budget_text(filters)}</b>\n"
            f"✅ Verified — <b>{verified}</b>\n"
            f"💸 Discount — <b>{discounted}</b>\n"
            f"↕️ စီစဉ်မှု — <b>{sort_labels[filters['sort']]}</b>\n"
            f"⌨️ Skin/Keyword — <b>{keyword}</b>\n\n"
            "လိုအပ်တာတွေရွေးပြီး <b>Account ရှာမယ်</b> ကိုနှိပ်ပါ။"
        )

    def search_menu(filters):
        menu = InlineKeyboardMarkup(row_width=2)
        menu.row(
            InlineKeyboardButton("💰 Budget", callback_data="adv_budget"),
            InlineKeyboardButton("⌨️ Skin ရိုက်မယ်", callback_data="adv_keyword"),
        )
        menu.row(
            InlineKeyboardButton(
                "✅ Verified ON" if filters["verified"] else "⬜ Verified",
                callback_data="adv_toggle_verified",
            ),
            InlineKeyboardButton(
                "✅ Discount ON" if filters["discounted"] else "⬜ Discount",
                callback_data="adv_toggle_discount",
            ),
        )
        menu.row(
            InlineKeyboardButton("↕️ စီစဉ်မယ်", callback_data="adv_sort"),
            InlineKeyboardButton("♻️ Reset", callback_data="adv_search_reset"),
        )
        menu.add(
            InlineKeyboardButton("🔍 Account ရှာမယ်", callback_data="adv_run")
        )
        menu.add(InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"))
        return menu

    def send_search_menu(chat_id, user_id, filters=None):
        filters = normalize_filters(filters or current_filters(user_id))
        save_search_state(user_id, filters)
        bot.send_message(
            chat_id,
            search_summary(filters),
            parse_mode="HTML",
            reply_markup=search_menu(filters),
        )

    def load_account(account_id):
        result = row(
            """
            SELECT a.*,
                   CASE
                       WHEN fd.ends_at > CURRENT_TIMESTAMP
                       THEN fd.deal_price
                       ELSE NULL
                   END AS adv_flash_price
            FROM accounts a
            LEFT JOIN premium_flash_deals fd ON fd.account_id=a.id
            WHERE a.id=?
            """,
            (int(account_id),),
        )
        if result is None:
            return None
        account = original.row_to_account(result)
        flash_price = 0
        try:
            flash_price = int(result["adv_flash_price"] or 0)
        except Exception:
            pass
        normal_effective = int(account.get("effective_price") or account.get("price") or 0)
        if flash_price > 0 and flash_price < normal_effective:
            account["effective_price"] = flash_price
            account["is_flash"] = True
            account["is_discounted"] = True
        else:
            account["is_flash"] = False
        try:
            account["is_verified"] = int(result["is_verified"] or 0)
        except Exception:
            account["is_verified"] = int(account.get("is_verified") or 0)
        return account

    def matching_accounts(filters):
        filters = normalize_filters(filters)
        raw_accounts = safe_rows(
            """
            SELECT a.id
            FROM accounts a
            WHERE a.status='available'
            ORDER BY a.id DESC
            """
        )
        keyword = filters["keyword"].casefold()
        matches = []
        for item in raw_accounts:
            account = load_account(int(item["id"]))
            if not account or account.get("status") != "available":
                continue
            price = int(account.get("effective_price") or 0)
            if filters["min_price"] and price < filters["min_price"]:
                continue
            if filters["max_price"] and price > filters["max_price"]:
                continue
            if filters["verified"] and not int(account.get("is_verified") or 0):
                continue
            if filters["discounted"] and not account.get("is_discounted"):
                continue
            if keyword:
                haystack = (
                    f"{account.get('id', '')} "
                    f"{account.get('title', '')} "
                    f"{account.get('skins', '')}"
                ).casefold()
                if keyword not in haystack:
                    continue
            matches.append(account)

        if filters["sort"] == "low":
            matches.sort(key=lambda a: (int(a.get("effective_price") or 0), int(a["db_id"])))
        elif filters["sort"] == "high":
            matches.sort(key=lambda a: (-int(a.get("effective_price") or 0), -int(a["db_id"])))
        else:
            matches.sort(key=lambda a: int(a["db_id"]), reverse=True)
        return matches

    def compact_account_text(account, index, total):
        original_price = int(account.get("price") or 0)
        effective_price = int(account.get("effective_price") or original_price)
        badges = []
        if int(account.get("is_verified") or 0):
            badges.append("✅ Verified")
        if account.get("is_flash"):
            badges.append("🔥 Flash Deal")
        elif account.get("is_discounted"):
            badges.append("💸 Discount")
        if account.get("is_new"):
            badges.append("🆕 New")
        if account.get("is_featured"):
            badges.append("⭐ Featured")

        badge_text = " • ".join(badges) if badges else "🎮 Marketplace Account"
        price_lines = f"💰 <b>{effective_price:,} MMK</b>"
        if effective_price < original_price:
            saved = original_price - effective_price
            percent = int(round(saved * 100 / original_price)) if original_price else 0
            price_lines = (
                f"💰 <s>{original_price:,} MMK</s> → "
                f"<b>{effective_price:,} MMK</b>\n"
                f"💸 သက်သာငွေ — <b>{saved:,} MMK ({percent}%)</b>"
            )

        skins = str(account.get("skins") or "Skin အချက်အလက် မထည့်ရသေးပါ")
        if len(skins) > 260:
            skins = skins[:257] + "..."

        return (
            f"🎯 <b>{index + 1}/{max(1, total)}</b>  •  "
            f"<b>{esc(account['id'])}</b>\n"
            f"{badge_text}\n\n"
            f"📝 <b>{esc(account.get('title') or 'ML Account')}</b>\n"
            f"✨ {esc(skins)}\n\n"
            f"{price_lines}\n"
            "🟢 <b>ဝယ်ယူနိုင်ပါသည်</b>"
        )

    def compact_account_menu(account, total):
        menu = InlineKeyboardMarkup(row_width=2)
        if total > 1:
            menu.row(
                InlineKeyboardButton("⬅️ အရင်", callback_data="adv_card_prev"),
                InlineKeyboardButton("နောက် ➡️", callback_data="adv_card_next"),
            )
        menu.row(
            InlineKeyboardButton(
                "🔎 ပုံ/အသေးစိတ်",
                callback_data=f"premium_account_detail_{account['id']}",
            ),
            InlineKeyboardButton(
                "❤️ သိမ်းထားမယ်",
                callback_data=f"premium_fav_toggle_{account['db_id']}",
            ),
        )
        menu.row(
            InlineKeyboardButton(
                "⚡ အမြန်ဝယ်မယ်",
                callback_data=f"premium_fast_buy_{account['id']}",
            ),
            InlineKeyboardButton(
                "🔔 ဈေးကျရင်ပြောမယ်",
                callback_data=f"premium_price_alert_{account['db_id']}",
            ),
        )
        menu.row(
            InlineKeyboardButton("🔧 Search ပြင်မယ်", callback_data="adv_search"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        return menu

    def show_search_card(chat_id, user_id, direction=0):
        state = original.get_state(int(user_id)) or {}
        ids = [int(value) for value in (state.get("adv_ids") or [])]
        if not ids:
            bot.send_message(
                chat_id,
                "❌ Search result မရှိတော့ပါ။ ပြန်ရှာပေးပါ။",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 ပြန်ရှာမယ်", callback_data="adv_search")]
                ]),
            )
            return

        index = int(state.get("adv_index", 0) or 0)
        index = (index + int(direction)) % len(ids)
        account = load_account(ids[index])
        if not account or account.get("status") != "available":
            filters = normalize_filters(state.get("adv_filters"))
            matches = matching_accounts(filters)
            ids = [int(item["db_id"]) for item in matches]
            if not ids:
                bot.send_message(
                    chat_id,
                    "❌ ကိုက်ညီတဲ့ Account မရှိတော့ပါ။",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔧 Search ပြင်မယ်", callback_data="adv_search")]
                    ]),
                )
                return
            index = 0
            account = matches[0]

        state["flow"] = "adv_results"
        state["adv_ids"] = ids
        state["adv_index"] = index
        original.set_state(int(user_id), state)

        text = compact_account_text(account, index, len(ids))
        markup = compact_account_menu(account, len(ids))
        photos = [photo for photo in (account.get("photos") or []) if photo]
        if photos:
            try:
                bot.send_photo(
                    chat_id,
                    photos[0],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                return
            except Exception:
                logging.exception(
                    "ADVANCED_CARD_PHOTO_FAILED account=%s",
                    account.get("id"),
                )
        bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=markup,
        )

    # ------------------------------------------------------------------
    # My Orders / My Sales
    # ------------------------------------------------------------------
    buy_status_labels = {
        "awaiting_receipt": "📸 ပြေစာပို့ရန်စောင့်နေသည်",
        "pending_admin": "⏳ Admin စစ်ဆေးနေသည်",
        "approved": "✅ အတည်ပြုပြီး",
        "rejected": "❌ ငြင်းပယ်ထားသည်",
        "cancelled": "🚫 ပယ်ဖျက်ထားသည်",
    }

    seller_status_labels = {
        "pending": "⏳ Admin စစ်ဆေးရန်စောင့်နေသည်",
        "accepted": "✅ Admin လက်ခံထားသည်",
        "rejected": "❌ ငြင်းပယ်ထားသည်",
        "awaiting_admin_price": "⏳ Admin စျေးပေးရန်စောင့်နေသည်",
        "awaiting_seller_offer_response": "💬 Seller အဖြေစောင့်နေသည်",
        "awaiting_admin_counter": "💬 Admin စျေးပြန်ပေးရန်စောင့်နေသည်",
        "seller_accepted_offer": "✅ Seller စျေးလက်ခံပြီး",
        "manual_moonton_transfer": "📧 Moonton ပြောင်းနေသည်",
        "awaiting_seller_gmail_access": "📧 Gmail ရယူရန်စောင့်နေသည်",
        "awaiting_moonton_proof": "📸 Moonton Proof စောင့်နေသည်",
        "awaiting_admin_seller_verify": "🔐 Admin အတည်ပြုရန်စောင့်နေသည်",
        "seller_verified_ready_for_payout": "💳 ငွေလွှဲနံပါတ်စောင့်နေသည်",
        "awaiting_admin_payout": "💸 Admin ငွေလွှဲရန်စောင့်နေသည်",
        "awaiting_seller_payout_confirmation": "✅ Seller ငွေရောက်ကြောင်းစောင့်နေသည်",
        "completed": "🎉 ပြီးဆုံးပြီ",
        "cancelled": "🚫 ပယ်ဖျက်ထားသည်",
    }

    def buy_status(value):
        return buy_status_labels.get(str(value or ""), f"ℹ️ {esc(value or '-')}")

    def seller_status(value):
        return seller_status_labels.get(str(value or ""), f"ℹ️ {esc(value or '-')}")

    def send_my_hub(chat_id, user_id):
        buy_count = int(scalar(
            "SELECT COUNT(*) FROM premium_buy_requests WHERE buyer_user_id=?",
            (int(user_id),),
        ) or 0)
        sale_count = int(scalar(
            "SELECT COUNT(*) FROM seller_requests WHERE user_id=?",
            (int(user_id),),
        ) or 0)
        active_buys = int(scalar(
            "SELECT COUNT(*) FROM premium_buy_requests "
            "WHERE buyer_user_id=? AND status NOT IN ('approved','rejected','cancelled')",
            (int(user_id),),
        ) or 0)
        active_sales = int(scalar(
            """
            SELECT COUNT(*)
            FROM seller_requests sr
            LEFT JOIN premium_seller_deals d ON d.request_id=sr.id
            WHERE sr.user_id=?
              AND COALESCE(d.status, sr.status) NOT IN ('completed','rejected','cancelled')
            """,
            (int(user_id),),
        ) or 0)

        menu = InlineKeyboardMarkup(row_width=1)
        menu.add(
            InlineKeyboardButton(
                f"🛒 ဝယ်ယူမှုများ ({buy_count})",
                callback_data="adv_my_buys",
            ),
            InlineKeyboardButton(
                f"💰 ရောင်းချမှုများ ({sale_count})",
                callback_data="adv_my_sales",
            ),
            InlineKeyboardButton("🔄 Refresh", callback_data="adv_my_hub"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        bot.send_message(
            chat_id,
            "📦 <b>ကျွန်ုပ်၏အော်ဒါများ / ရောင်းထားမှုများ</b>\n\n"
            f"🛒 ဝယ်ယူမှုစုစုပေါင်း — <b>{buy_count}</b>\n"
            f"⏳ လုပ်ဆောင်နေသောဝယ်ယူမှု — <b>{active_buys}</b>\n"
            f"💰 ရောင်းချမှုစုစုပေါင်း — <b>{sale_count}</b>\n"
            f"⏳ လုပ်ဆောင်နေသောရောင်းချမှု — <b>{active_sales}</b>",
            parse_mode="HTML",
            reply_markup=menu,
        )

    def send_my_buys(chat_id, user_id):
        items = safe_rows(
            """
            SELECT id, account_id, account_code, price, status,
                   created_at, updated_at
            FROM premium_buy_requests
            WHERE buyer_user_id=?
            ORDER BY id DESC
            LIMIT 30
            """,
            (int(user_id),),
        )
        if not items:
            bot.send_message(
                chat_id,
                "🛒 ဝယ်ယူမှုမှတ်တမ်း မရှိသေးပါ။",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 ပြန်သွားမယ်", callback_data="adv_my_hub")]
                ]),
            )
            return
        menu = InlineKeyboardMarkup(row_width=1)
        for item in items:
            label = (
                f"BUY-{int(item['id']):04d} • {item['account_code']} • "
                f"{int(item['price'] or 0):,}"
            )
            menu.add(
                InlineKeyboardButton(
                    label,
                    callback_data=f"adv_my_buy_{int(item['id'])}",
                )
            )
        menu.add(InlineKeyboardButton("🔙 ပြန်သွားမယ်", callback_data="adv_my_hub"))
        bot.send_message(
            chat_id,
            "🛒 <b>ဝယ်ယူမှုများ</b>\n\nအသေးစိတ်ကြည့်ရန် အော်ဒါကိုရွေးပါ။",
            parse_mode="HTML",
            reply_markup=menu,
        )

    def send_my_buy_detail(chat_id, user_id, request_id):
        item = row(
            """
            SELECT * FROM premium_buy_requests
            WHERE id=? AND buyer_user_id=?
            """,
            (int(request_id), int(user_id)),
        )
        if item is None:
            bot.send_message(chat_id, "❌ ဒီအော်ဒါကို ရှာမတွေ့ပါ။")
            return
        menu = InlineKeyboardMarkup(row_width=1)
        if int(item["account_id"] or 0) > 0:
            menu.add(
                InlineKeyboardButton(
                    "🎮 Account ကြည့်မယ်",
                    callback_data=f"premium_account_detail_{item['account_code']}",
                )
            )
        menu.add(
            InlineKeyboardButton("🔙 ဝယ်ယူမှုများ", callback_data="adv_my_buys"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        bot.send_message(
            chat_id,
            "🛒 <b>ဝယ်ယူမှုအသေးစိတ်</b>\n\n"
            f"🆔 BUY-{int(item['id']):04d}\n"
            f"🎮 Account — <b>{esc(item['account_code'])}</b>\n"
            f"💰 ပမာဏ — <b>{int(item['price'] or 0):,} MMK</b>\n"
            f"📌 အခြေအနေ — <b>{buy_status(item['status'])}</b>\n"
            f"🕒 စတင်ချိန် — <code>{esc(item['created_at'])}</code>\n"
            f"🔄 နောက်ဆုံးပြင်ချိန် — <code>{esc(item['updated_at'])}</code>",
            parse_mode="HTML",
            reply_markup=menu,
        )

    def seller_records(user_id, limit=30):
        return safe_rows(
            """
            SELECT sr.*,
                   d.status AS deal_status,
                   d.admin_offer_price,
                   d.payout_amount,
                   d.payout_destination,
                   d.updated_at AS deal_updated_at
            FROM seller_requests sr
            LEFT JOIN premium_seller_deals d ON d.request_id=sr.id
            WHERE sr.user_id=?
            ORDER BY sr.id DESC
            LIMIT ?
            """,
            (int(user_id), int(limit)),
        )

    def send_my_sales(chat_id, user_id):
        items = seller_records(user_id)
        if not items:
            bot.send_message(
                chat_id,
                "💰 ရောင်းချမှုမှတ်တမ်း မရှိသေးပါ။",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 ပြန်သွားမယ်", callback_data="adv_my_hub")]
                ]),
            )
            return
        menu = InlineKeyboardMarkup(row_width=1)
        for item in items:
            status_value = item["deal_status"] or item["status"]
            icon = "🎉" if status_value == "completed" else "⏳"
            menu.add(
                InlineKeyboardButton(
                    f"{icon} SELL-{int(item['id']):04d} • "
                    f"{int(item['price'] or 0):,} MMK",
                    callback_data=f"adv_my_sale_{int(item['id'])}",
                )
            )
        menu.add(InlineKeyboardButton("🔙 ပြန်သွားမယ်", callback_data="adv_my_hub"))
        bot.send_message(
            chat_id,
            "💰 <b>ရောင်းချမှုများ</b>\n\nအသေးစိတ်ကြည့်ရန် Request ကိုရွေးပါ။",
            parse_mode="HTML",
            reply_markup=menu,
        )

    def mask_destination(value):
        text = str(value or "").strip()
        if len(text) <= 4:
            return text or "မထည့်ရသေး"
        return "•" * max(3, len(text) - 4) + text[-4:]

    def send_my_sale_detail(chat_id, user_id, request_id):
        items = safe_rows(
            """
            SELECT sr.*,
                   d.status AS deal_status,
                   d.seller_expected_price,
                   d.seller_note,
                   d.admin_offer_price,
                   d.payout_amount,
                   d.payout_destination,
                   d.updated_at AS deal_updated_at
            FROM seller_requests sr
            LEFT JOIN premium_seller_deals d ON d.request_id=sr.id
            WHERE sr.id=? AND sr.user_id=?
            """,
            (int(request_id), int(user_id)),
        )
        if not items:
            bot.send_message(chat_id, "❌ ဒီ Seller Request ကို ရှာမတွေ့ပါ။")
            return
        item = items[0]
        status_value = item["deal_status"] or item["status"]
        menu = InlineKeyboardMarkup(row_width=1)
        menu.add(
            InlineKeyboardButton("🔄 Refresh", callback_data=f"adv_my_sale_{request_id}"),
            InlineKeyboardButton("🔙 ရောင်းချမှုများ", callback_data="adv_my_sales"),
            InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home"),
        )
        bot.send_message(
            chat_id,
            "💰 <b>ရောင်းချမှုအသေးစိတ်</b>\n\n"
            f"🆔 SELL-{int(item['id']):04d}\n"
            f"📌 အခြေအနေ — <b>{seller_status(status_value)}</b>\n"
            f"💭 Seller ခန့်မှန်းဈေး — <b>{int(item['seller_expected_price'] or item['price'] or 0):,} MMK</b>\n"
            f"🤝 Admin ပေးဈေး — <b>{int(item['admin_offer_price'] or 0):,} MMK</b>\n"
            f"💸 Payout — <b>{int(item['payout_amount'] or 0):,} MMK</b>\n"
            f"💳 လွှဲမည့်နေရာ — <code>{esc(mask_destination(item['payout_destination']))}</code>\n"
            f"🕒 စတင်ချိန် — <code>{esc(item['created_at'])}</code>\n"
            f"🔄 နောက်ဆုံးပြင်ချိန် — <code>{esc(item['deal_updated_at'] or item['created_at'])}</code>",
            parse_mode="HTML",
            reply_markup=menu,
        )

    # ------------------------------------------------------------------
    # Admin Pending Queue
    # ------------------------------------------------------------------
    def queue_counts():
        return {
            "buy": int(scalar(
                "SELECT COUNT(*) FROM premium_buy_requests WHERE status='pending_admin'"
            ) or 0),
            "seller": int(scalar(
                """
                SELECT COUNT(*)
                FROM seller_requests sr
                LEFT JOIN premium_seller_deals d ON d.request_id=sr.id
                WHERE (d.status IN ('awaiting_admin_price','awaiting_admin_counter'))
                   OR (d.request_id IS NULL AND sr.status='pending')
                """
            ) or 0),
            "verify": int(scalar(
                "SELECT COUNT(*) FROM premium_seller_deals "
                "WHERE status='awaiting_admin_seller_verify'"
            ) or 0),
            "payout": int(scalar(
                "SELECT COUNT(*) FROM premium_seller_deals "
                "WHERE status='awaiting_admin_payout'"
            ) or 0),
        }

    def send_admin_queue(chat_id):
        counts = queue_counts()
        total = sum(counts.values())
        menu = InlineKeyboardMarkup(row_width=1)
        menu.add(
            InlineKeyboardButton(
                f"🧾 Buyer ပြေစာစစ်ရန် ({counts['buy']})",
                callback_data="adv_queue_buy",
            ),
            InlineKeyboardButton(
                f"💰 Seller စျေး/Request ({counts['seller']})",
                callback_data="adv_queue_seller",
            ),
            InlineKeyboardButton(
                f"🔐 Moonton Proof စစ်ရန် ({counts['verify']})",
                callback_data="adv_queue_verify",
            ),
            InlineKeyboardButton(
                f"💸 Seller ငွေလွှဲရန် ({counts['payout']})",
                callback_data="adv_queue_payout",
            ),
            InlineKeyboardButton("🔄 Refresh", callback_data="adv_admin_queue"),
            InlineKeyboardButton("📊 Dashboard", callback_data="adv_admin_dashboard"),
            InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"),
        )
        bot.send_message(
            chat_id,
            "🗂️ <b>Admin Pending Queue</b>\n\n"
            f"🔔 လုပ်ဆောင်ရန်စုစုပေါင်း — <b>{total}</b>\n\n"
            f"🧾 Buyer ပြေစာ — <b>{counts['buy']}</b>\n"
            f"💰 Seller စျေး/Request — <b>{counts['seller']}</b>\n"
            f"🔐 Moonton Proof — <b>{counts['verify']}</b>\n"
            f"💸 Seller Payout — <b>{counts['payout']}</b>",
            parse_mode="HTML",
            reply_markup=menu,
        )

    def send_buy_queue(chat_id):
        items = safe_rows(
            """
            SELECT id, account_code, price, buyer_user_id, created_at
            FROM premium_buy_requests
            WHERE status='pending_admin'
            ORDER BY updated_at ASC
            LIMIT 30
            """
        )
        menu = InlineKeyboardMarkup(row_width=1)
        if items:
            for item in items:
                menu.add(
                    InlineKeyboardButton(
                        f"🧾 BUY-{int(item['id']):04d} • {item['account_code']} • "
                        f"{int(item['price'] or 0):,}",
                        callback_data=f"adv_queue_buy_detail_{int(item['id'])}",
                    )
                )
        menu.add(InlineKeyboardButton("🔙 Pending Queue", callback_data="adv_admin_queue"))
        text = "🧾 <b>စစ်ရန် Buyer ပြေစာများ</b>"
        if not items:
            text += "\n\n✅ လက်ရှိစစ်ရန် မရှိပါ။"
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=menu)

    def send_buy_queue_detail(chat_id, request_id):
        item = row(
            "SELECT * FROM premium_buy_requests WHERE id=? AND status='pending_admin'",
            (int(request_id),),
        )
        if item is None:
            bot.send_message(
                chat_id,
                "ℹ️ ဒီ Buyer Request ကို စစ်ပြီးသား သို့မဟုတ် မရှိတော့ပါ။",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Buyer Queue", callback_data="adv_queue_buy")]
                ]),
            )
            return
        menu = InlineKeyboardMarkup(row_width=2)
        menu.row(
            InlineKeyboardButton(
                "✅ အတည်ပြုမယ်",
                callback_data=f"premium_buy_admin_approve_{request_id}",
            ),
            InlineKeyboardButton(
                "❌ ငြင်းမယ်",
                callback_data=f"premium_buy_admin_reject_{request_id}",
            ),
        )
        menu.add(InlineKeyboardButton("🔙 Buyer Queue", callback_data="adv_queue_buy"))
        caption = (
            "🧾 <b>Buyer Receipt Review</b>\n\n"
            f"🆔 BUY-{int(item['id']):04d}\n"
            f"👤 Buyer — <code>{int(item['buyer_user_id'])}</code>\n"
            f"🎮 Account — <b>{esc(item['account_code'])}</b>\n"
            f"💰 ပမာဏ — <b>{int(item['price'] or 0):,} MMK</b>"
        )
        try:
            if item["receipt_type"] == "photo" and item["receipt_file_id"]:
                bot.send_photo(
                    chat_id,
                    item["receipt_file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=menu,
                )
                return
            if item["receipt_type"] == "document" and item["receipt_file_id"]:
                bot.send_document(
                    chat_id,
                    item["receipt_file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=menu,
                )
                return
        except Exception:
            logging.exception("ADVANCED_BUY_RECEIPT_DISPLAY_FAILED request=%s", request_id)
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=menu)

    def send_seller_queue(chat_id):
        items = safe_rows(
            """
            SELECT sr.id, sr.user_id, sr.username, sr.price, sr.status,
                   d.status AS deal_status
            FROM seller_requests sr
            LEFT JOIN premium_seller_deals d ON d.request_id=sr.id
            WHERE d.status IN ('awaiting_admin_price','awaiting_admin_counter')
               OR (d.request_id IS NULL AND sr.status='pending')
            ORDER BY sr.id ASC
            LIMIT 30
            """
        )
        menu = InlineKeyboardMarkup(row_width=1)
        for item in items:
            deal_status = item["deal_status"]
            callback = (
                f"premium_seller_offer_{int(item['id'])}"
                if deal_status
                else f"seller_view_{int(item['id'])}"
            )
            menu.add(
                InlineKeyboardButton(
                    f"💰 SELL-{int(item['id']):04d} • "
                    f"{int(item['price'] or 0):,} MMK",
                    callback_data=callback,
                )
            )
        menu.add(InlineKeyboardButton("🔙 Pending Queue", callback_data="adv_admin_queue"))
        text = "💰 <b>Seller စျေး/Request Queue</b>"
        if not items:
            text += "\n\n✅ လက်ရှိလုပ်ဆောင်ရန် မရှိပါ။"
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=menu)

    def send_verify_queue(chat_id):
        items = safe_rows(
            """
            SELECT d.request_id, d.seller_user_id, d.updated_at
            FROM premium_seller_deals d
            WHERE d.status='awaiting_admin_seller_verify'
            ORDER BY d.updated_at ASC
            LIMIT 30
            """
        )
        menu = InlineKeyboardMarkup(row_width=1)
        for item in items:
            request_id = int(item["request_id"])
            menu.add(
                InlineKeyboardButton(
                    f"🔐 SELL-{request_id:04d} • Seller {int(item['seller_user_id'])}",
                    callback_data=f"premium_seller_admin_verify_{request_id}",
                )
            )
        menu.add(InlineKeyboardButton("🔙 Pending Queue", callback_data="adv_admin_queue"))
        text = "🔐 <b>Moonton Proof စစ်ရန်</b>"
        if not items:
            text += "\n\n✅ လက်ရှိစစ်ရန် မရှိပါ။"
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=menu)

    def send_payout_queue(chat_id):
        items = safe_rows(
            """
            SELECT request_id, seller_user_id, payout_amount,
                   payout_destination, updated_at
            FROM premium_seller_deals
            WHERE status='awaiting_admin_payout'
            ORDER BY updated_at ASC
            LIMIT 30
            """
        )
        menu = InlineKeyboardMarkup(row_width=1)
        for item in items:
            request_id = int(item["request_id"])
            menu.add(
                InlineKeyboardButton(
                    f"💸 SELL-{request_id:04d} • "
                    f"{int(item['payout_amount'] or 0):,} MMK",
                    callback_data=f"premium_admin_send_payout_receipt_{request_id}",
                )
            )
        menu.add(InlineKeyboardButton("🔙 Pending Queue", callback_data="adv_admin_queue"))
        text = "💸 <b>Seller ငွေလွှဲရန် Queue</b>"
        if not items:
            text += "\n\n✅ လက်ရှိငွေလွှဲရန် မရှိပါ။"
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=menu)

    # ------------------------------------------------------------------
    # Admin Dashboard
    # ------------------------------------------------------------------
    def price_bands():
        values = safe_rows(
            "SELECT price FROM premium_buy_requests WHERE status='approved'"
        )
        bands = {
            "0–50K": 0,
            "50K–100K": 0,
            "100K–200K": 0,
            "200K–300K": 0,
            "300K+": 0,
        }
        for item in values:
            price = int(item["price"] or 0)
            if price <= 50000:
                bands["0–50K"] += 1
            elif price <= 100000:
                bands["50K–100K"] += 1
            elif price <= 200000:
                bands["100K–200K"] += 1
            elif price <= 300000:
                bands["200K–300K"] += 1
            else:
                bands["300K+"] += 1
        return bands

    def send_admin_dashboard(chat_id):
        counts = queue_counts()
        pending_total = sum(counts.values())
        completed_buys = int(scalar(
            "SELECT COUNT(*) FROM premium_buy_requests WHERE status='approved'"
        ) or 0)
        revenue_total = int(scalar(
            "SELECT COALESCE(SUM(price),0) FROM premium_buy_requests WHERE status='approved'"
        ) or 0)
        revenue_7d = int(scalar(
            "SELECT COALESCE(SUM(price),0) FROM premium_buy_requests "
            "WHERE status='approved' AND updated_at >= datetime('now','-7 days')"
        ) or 0)
        revenue_30d = int(scalar(
            "SELECT COALESCE(SUM(price),0) FROM premium_buy_requests "
            "WHERE status='approved' AND updated_at >= datetime('now','-30 days')"
        ) or 0)
        completed_sales = int(scalar(
            "SELECT COUNT(*) FROM premium_seller_deals WHERE status='completed'"
        ) or 0)
        payouts = int(scalar(
            "SELECT COALESCE(SUM(payout_amount),0) FROM premium_seller_deals "
            "WHERE status='completed'"
        ) or 0)
        users = int(scalar("SELECT COUNT(*) FROM users") or 0)
        available = int(scalar(
            "SELECT COUNT(*) FROM accounts WHERE status='available'"
        ) or 0)
        sold = int(scalar(
            "SELECT COUNT(*) FROM accounts WHERE status='sold'"
        ) or 0)
        discounted = int(scalar(
            "SELECT COUNT(*) FROM accounts WHERE status='available' "
            "AND sale_price IS NOT NULL AND sale_price > 0 AND sale_price < price"
        ) or 0)
        bands = price_bands()
        popular_name, popular_count = max(bands.items(), key=lambda item: item[1])
        popular_text = (
            f"{popular_name} ({popular_count} orders)"
            if popular_count
            else "အချက်အလက်မရှိသေး"
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        menu = InlineKeyboardMarkup(row_width=2)
        menu.row(
            InlineKeyboardButton("🔄 Refresh", callback_data="adv_admin_dashboard"),
            InlineKeyboardButton("🗂️ Pending Queue", callback_data="adv_admin_queue"),
        )
        menu.add(InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"))

        bot.send_message(
            chat_id,
            "📊 <b>Admin Dashboard</b>\n\n"
            "💵 <b>Buyer Revenue</b>\n"
            f"• 7 ရက် — <b>{revenue_7d:,} MMK</b>\n"
            f"• 30 ရက် — <b>{revenue_30d:,} MMK</b>\n"
            f"• စုစုပေါင်း — <b>{revenue_total:,} MMK</b>\n"
            f"• Completed Orders — <b>{completed_buys}</b>\n\n"
            "💰 <b>Seller Side</b>\n"
            f"• Completed Sales — <b>{completed_sales}</b>\n"
            f"• Completed Payouts — <b>{payouts:,} MMK</b>\n\n"
            "📦 <b>Inventory</b>\n"
            f"• Available — <b>{available}</b>\n"
            f"• Sold — <b>{sold}</b>\n"
            f"• Discounted — <b>{discounted}</b>\n\n"
            "📈 <b>Operations</b>\n"
            f"• Users — <b>{users}</b>\n"
            f"• Pending Actions — <b>{pending_total}</b>\n"
            f"• Popular Price Range — <b>{popular_text}</b>\n\n"
            f"🕒 <code>{timestamp}</code>",
            parse_mode="HTML",
            reply_markup=menu,
        )

    # ------------------------------------------------------------------
    # Callback router
    # ------------------------------------------------------------------
    def handle_callback(call):
        data = str(call.data or "")
        user_id = int(call.from_user.id)
        chat_id = int(call.message.chat.id)

        # Check protected routes before acknowledging the callback so a
        # non-admin still receives Telegram's visible alert response.
        protected = data.startswith("adv_admin_") or data.startswith("adv_queue_")
        if protected and user_id != admin_id:
            safe_answer(call, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", True)
            return
        safe_answer(call)

        if data == "adv_search":
            send_search_menu(chat_id, user_id)
            return
        if data == "adv_search_reset":
            send_search_menu(chat_id, user_id, default_filters)
            return
        if data == "adv_budget":
            menu = InlineKeyboardMarkup(row_width=2)
            for key, (_, _, label) in budget_presets.items():
                menu.add(
                    InlineKeyboardButton(
                        f"💰 {label}",
                        callback_data=f"adv_budget_set_{key}",
                    )
                )
            menu.add(InlineKeyboardButton("🔙 Search", callback_data="adv_search"))
            bot.send_message(chat_id, "💰 <b>Budget ရွေးပါ</b>", parse_mode="HTML", reply_markup=menu)
            return
        if data.startswith("adv_budget_set_"):
            key = data.replace("adv_budget_set_", "", 1)
            if key in budget_presets:
                filters = current_filters(user_id)
                filters["min_price"], filters["max_price"], _ = budget_presets[key]
                send_search_menu(chat_id, user_id, filters)
            return
        if data == "adv_toggle_verified":
            filters = current_filters(user_id)
            filters["verified"] = 0 if filters["verified"] else 1
            send_search_menu(chat_id, user_id, filters)
            return
        if data == "adv_toggle_discount":
            filters = current_filters(user_id)
            filters["discounted"] = 0 if filters["discounted"] else 1
            send_search_menu(chat_id, user_id, filters)
            return
        if data == "adv_sort":
            menu = InlineKeyboardMarkup(row_width=1)
            for key, label in sort_labels.items():
                menu.add(
                    InlineKeyboardButton(
                        f"↕️ {label}",
                        callback_data=f"adv_sort_set_{key}",
                    )
                )
            menu.add(InlineKeyboardButton("🔙 Search", callback_data="adv_search"))
            bot.send_message(chat_id, "↕️ <b>စီစဉ်ပုံရွေးပါ</b>", parse_mode="HTML", reply_markup=menu)
            return
        if data.startswith("adv_sort_set_"):
            key = data.replace("adv_sort_set_", "", 1)
            filters = current_filters(user_id)
            if key in sort_labels:
                filters["sort"] = key
            send_search_menu(chat_id, user_id, filters)
            return
        if data == "adv_keyword":
            filters = current_filters(user_id)
            save_search_state(user_id, filters, flow="adv_keyword")
            menu = InlineKeyboardMarkup(row_width=1)
            if filters["keyword"]:
                menu.add(
                    InlineKeyboardButton(
                        "🗑️ Keyword ဖျက်မယ်",
                        callback_data="adv_keyword_clear",
                    )
                )
            menu.add(InlineKeyboardButton("🔙 Search", callback_data="adv_search"))
            bot.send_message(
                chat_id,
                "⌨️ <b>ရှာချင်တဲ့ Skin/Account နာမည်ကို ရိုက်ပို့ပါ။</b>\n\n"
                "ဥပမာ — <code>Gusion</code>",
                parse_mode="HTML",
                reply_markup=menu,
            )
            return
        if data == "adv_keyword_clear":
            filters = current_filters(user_id)
            filters["keyword"] = ""
            send_search_menu(chat_id, user_id, filters)
            return
        if data == "adv_run":
            filters = current_filters(user_id)
            matches = matching_accounts(filters)
            if not matches:
                bot.send_message(
                    chat_id,
                    "😕 သတ်မှတ်ထားတဲ့ Filter နဲ့ ကိုက်ညီတဲ့ Account မတွေ့ပါ။\n\n"
                    "Budget/Verified/Keyword ကို ပြန်ပြင်ကြည့်ပါ။",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔧 Search ပြင်မယ်", callback_data="adv_search")],
                        [InlineKeyboardButton("♻️ Filter Reset", callback_data="adv_search_reset")],
                    ]),
                )
                return
            save_search_state(
                user_id,
                filters,
                flow="adv_results",
                adv_ids=[int(item["db_id"]) for item in matches],
                adv_index=0,
            )
            log_action(call.from_user, "advanced_search", f"results={len(matches)}")
            bot.send_message(
                chat_id,
                f"✅ ကိုက်ညီတဲ့ Account <b>{len(matches)}</b> ခု တွေ့ပါတယ်။",
                parse_mode="HTML",
            )
            show_search_card(chat_id, user_id)
            return
        if data in {"adv_card_prev", "adv_card_next"}:
            show_search_card(chat_id, user_id, -1 if data.endswith("prev") else 1)
            return

        if data == "adv_my_hub":
            send_my_hub(chat_id, user_id)
            return
        if data == "adv_my_buys":
            send_my_buys(chat_id, user_id)
            return
        if data.startswith("adv_my_buy_"):
            send_my_buy_detail(chat_id, user_id, int(data.replace("adv_my_buy_", "", 1)))
            return
        if data == "adv_my_sales":
            send_my_sales(chat_id, user_id)
            return
        if data.startswith("adv_my_sale_"):
            send_my_sale_detail(chat_id, user_id, int(data.replace("adv_my_sale_", "", 1)))
            return

        if data == "adv_admin_queue":
            if is_admin(call):
                send_admin_queue(chat_id)
            return
        if data == "adv_queue_buy":
            if is_admin(call):
                send_buy_queue(chat_id)
            return
        if data.startswith("adv_queue_buy_detail_"):
            if is_admin(call):
                send_buy_queue_detail(
                    chat_id,
                    int(data.replace("adv_queue_buy_detail_", "", 1)),
                )
            return
        if data == "adv_queue_seller":
            if is_admin(call):
                send_seller_queue(chat_id)
            return
        if data == "adv_queue_verify":
            if is_admin(call):
                send_verify_queue(chat_id)
            return
        if data == "adv_queue_payout":
            if is_admin(call):
                send_payout_queue(chat_id)
            return
        if data == "adv_admin_dashboard":
            if is_admin(call):
                send_admin_dashboard(chat_id)
            return

    # ------------------------------------------------------------------
    # Update interceptor. It is installed last, before the bot starts.
    # ------------------------------------------------------------------
    previous_process = bot.process_new_updates
    if not hasattr(bot, "_advanced_v1_previous_process"):
        bot._advanced_v1_previous_process = previous_process

        def intercepted_process(updates):
            remaining = []
            for update in updates or []:
                message = getattr(update, "message", None)
                if message is not None:
                    text_value = (getattr(message, "text", None) or "").strip()
                    if text_value == "/start":
                        try:
                            original.clear_state(message.from_user.id)
                        except Exception:
                            pass
                        log_action(message.from_user, "start_advanced")
                        send_home(
                            message.chat.id,
                            message.from_user.id,
                            with_reply_keyboard=True,
                        )
                        continue

                    state = original.get_state(message.from_user.id) or {}
                    if state.get("flow") == "adv_keyword" and text_value:
                        filters = normalize_filters(state.get("adv_filters"))
                        filters["keyword"] = text_value[:80]
                        send_search_menu(
                            message.chat.id,
                            message.from_user.id,
                            filters,
                        )
                        continue

                call = getattr(update, "callback_query", None)
                if call is not None:
                    data = str(call.data or "")
                    if data == "home":
                        safe_answer(call)
                        try:
                            original.clear_state(call.from_user.id)
                        except Exception:
                            pass
                        send_home(call.message.chat.id, call.from_user.id)
                        continue
                    if data.startswith("adv_"):
                        try:
                            handle_callback(call)
                        except Exception:
                            logging.exception("ADVANCED_CALLBACK_FAILED data=%s", data)
                            safe_answer(call)
                            try:
                                bot.send_message(
                                    call.message.chat.id,
                                    "❌ ဒီလုပ်ဆောင်ချက်မှာ အမှားရှိနေပါတယ်။ "
                                    "ပင်မ Menu ကိုပြန်ပြီး ထပ်စမ်းပေးပါ။",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("🏠 ပင်မ Menu", callback_data="home")]
                                    ]),
                                )
                            except Exception:
                                pass
                        continue
                remaining.append(update)

            if remaining:
                return bot._advanced_v1_previous_process(remaining)
            return None

        bot.process_new_updates = intercepted_process

    logging.info("ADVANCED_MARKETPLACE_V1_READY")
