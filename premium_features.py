"""
MLBB MARKET - Premium Features Module
--------------------------------------
Standalone feature module. This file does NOT replace or rewrite main.py.

Features included:
1) ⚡ အမြန်ဝယ်မယ်
2) 🔥 Flash Deal
3) 🔔 ဈေးကျရင် အသိပေးမယ်
4) ✅ Account Verified
5) 👤 ကျွန်ုပ်၏အကောင့်
6) 🆕 အသစ်တင်ထားတဲ့အကောင့်များ
7) 🔎 အဆင့်မြင့်ရှာဖွေမယ်
8) 🔔 အသစ်တင်အကောင့် အသိပေးချက်
9) ❤️ သိမ်းထားတဲ့အကောင့်များ

Integration design:
- Import this module from the external launcher (or another bootstrap file).
- The original main.py remains untouched.
- The module creates only its own premium_* tables.
- Existing account rows are read from the original SQLite DB.
- Existing account IDs / photos / prices / statuses are not deleted or rewritten.

Expected integration call:
    premium_features.install(
        bot=original.bot,
        db_connect=original.db_connect,
        db_lock=original.db_lock,
        admin_id=original.ADMIN_ID,
        get_available_accounts=original.get_available_accounts,
        get_account_by_text_id=original.get_account_by_text_id,
        make_account_id=original.make_account_id,
        log_user_activity=getattr(original, "log_user_activity", None),
    )

The module is intentionally independent from Supabase persistence. Keep the
Supabase launcher and main.py as separate files.
"""

from __future__ import annotations

import html
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup


INSTALLED = False


def _safe_text(value: Any) -> str:
    return html.escape(str(value or ""))


def _price(acc: dict[str, Any]) -> int:
    try:
        return int(acc.get("effective_price") or acc.get("sale_price") or acc.get("price") or 0)
    except Exception:
        return 0


def _account_label(acc: dict[str, Any]) -> str:
    status_map = {
        "available": "🟢 ရရှိနိုင်",
        "reserved": "🟡 ခဏယူထား",
        "sold": "🔴 ရောင်းပြီး",
        "hidden": "⚫ ဖျောက်ထား",
    }
    skins = " ".join(str(acc.get("skins") or "").replace("\n", " ").split())
    if len(skins) > 90:
        skins = skins[:89].rstrip() + "…"
    lines = [
        f"🆔 <b>{_safe_text(acc.get('id'))}</b>",
        "🎮 <b>ML Account</b>",
        f"📌 {status_map.get(acc.get('status'), _safe_text(acc.get('status')))}",
    ]
    if acc.get("is_new"):
        lines.append("🆕 <b>အသစ်တင်ထားသည်</b>")
    if acc.get("is_verified"):
        lines.append("✅ <b>Admin စစ်ဆေးပြီး</b>")
    if skins:
        lines.append(f"🎨 <b>Skin:</b> {_safe_text(skins)}")
    lines.append(f"💰 <b>{_price(acc):,} MMK</b>")
    return "\n".join(lines)


def _menu(buttons: list[list[tuple[str, str]]], row_width: int = 2) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=row_width)
    for row in buttons:
        markup.row(*[InlineKeyboardButton(text, callback_data=data) for text, data in row])
    return markup


def _connect(db_connect: Callable[[], sqlite3.Connection]):
    return closing(db_connect())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(db_connect: Callable[[], sqlite3.Connection], db_lock) -> None:
    with db_lock:
        with _connect(db_connect) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_favorites (
                    user_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, account_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_alerts (
                    user_id INTEGER PRIMARY KEY,
                    max_price INTEGER,
                    skin_keyword TEXT NOT NULL DEFAULT '',
                    new_accounts INTEGER NOT NULL DEFAULT 0,
                    price_drops INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_views (
                    user_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, account_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_recent_searches (
                    user_id INTEGER PRIMARY KEY,
                    skin_keyword TEXT NOT NULL DEFAULT '',
                    max_price INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Verified flag is intentionally added only if it does not exist.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
            if "is_verified" not in cols:
                conn.execute(
                    "ALTER TABLE accounts ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
                )
            if "flash_deal_price" not in cols:
                conn.execute("ALTER TABLE accounts ADD COLUMN flash_deal_price INTEGER")
            if "flash_deal_until" not in cols:
                conn.execute("ALTER TABLE accounts ADD COLUMN flash_deal_until TEXT")
            conn.commit()


def _get_rows(
    db_connect: Callable[[], sqlite3.Connection],
    db_lock,
    sql: str,
    params: tuple = (),
):
    with db_lock:
        with _connect(db_connect) as conn:
            return conn.execute(sql, params).fetchall()


def _get_one(
    db_connect: Callable[[], sqlite3.Connection],
    db_lock,
    sql: str,
    params: tuple = (),
):
    with db_lock:
        with _connect(db_connect) as conn:
            return conn.execute(sql, params).fetchone()


def _is_alert_enabled(row) -> bool:
    return bool(row and int(row["enabled"] or 0))


def _build_feature_menu() -> InlineKeyboardMarkup:
    return _menu(
        [
            [("⚡ အမြန်ဝယ်မယ်", "pf_quick_buy"), ("🔥 Flash Deal", "pf_flash")],
            [("🔎 အဆင့်မြင့်ရှာဖွေမယ်", "pf_advanced")],
            [("🆕 အသစ်တင်ထားတဲ့အကောင့်များ", "pf_new")],
            [("❤️ သိမ်းထားတဲ့အကောင့်များ", "pf_favorites")],
            [("🔔 အသစ်တင်/ဈေးကျ အသိပေးချက်", "pf_alerts")],
            [("👤 ကျွန်ုပ်၏အကောင့်", "pf_profile")],
            [("🏠 ပင်မ Menu", "home")],
        ],
        row_width=2,
    )


def _account_buttons(
    account: dict[str, Any],
    include_favorite: bool = True,
    include_quick_buy: bool = True,
    back_callback: str = "pf_menu",
) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if account.get("status") == "available":
        if include_quick_buy:
            rows.append([("⚡ အမြန်ဝယ်မယ်", f"pf_quick_{account['id']}")])
        rows.append([("🛒 ဒီအကောင့် ဝယ်မယ်", f"buy_confirm_{account['id']}")])
    if include_favorite:
        rows.append([("❤️ သိမ်းထားမယ်", f"pf_fav_add_{account['id']}")])
    rows.append([("➡️ နောက်အကောင့်", f"pf_next_{account['id']}")])
    rows.append([("🔙 Feature Menu", back_callback)])
    return _menu(rows, row_width=2)


def _eligible_accounts(
    get_available_accounts: Callable[[], list[dict[str, Any]]],
    include_sold: bool = False,
) -> list[dict[str, Any]]:
    if not include_sold:
        return list(get_available_accounts())
    return []


def install(
    *,
    bot,
    db_connect: Callable[[], sqlite3.Connection],
    db_lock,
    admin_id: int,
    get_available_accounts: Callable[[], list[dict[str, Any]]],
    get_account_by_text_id: Callable[[str], Optional[dict[str, Any]]],
    make_account_id: Callable[[int], str] | None = None,
    log_user_activity: Callable[..., Any] | None = None,
):
    """Install all premium feature handlers into an existing TeleBot instance."""
    global INSTALLED
    if INSTALLED:
        return

    _ensure_tables(db_connect, db_lock)

    def log(user, action: str, details: str = ""):
        if log_user_activity:
            try:
                log_user_activity(user, action, details)
            except Exception:
                pass

    def feature_menu_message(chat_id: int):
        bot.send_message(
            chat_id,
            "✨ <b>Premium Features</b>\n\nလိုအပ်တဲ့ Feature ကို ရွေးပါ။",
            parse_mode="HTML",
            reply_markup=_build_feature_menu(),
        )

    @bot.message_handler(commands=["features", "premium"])
    def premium_command(message):
        log(message.from_user, "premium_features")
        feature_menu_message(message.chat.id)

    @bot.callback_query_handler(func=lambda c: c.data == "pf_menu")
    def pf_menu(call):
        bot.answer_callback_query(call.id)
        feature_menu_message(call.message.chat.id)

    # ------------------------------------------------------------------
    # ❤️ Favorites
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_favorites")
    def pf_favorites(call):
        bot.answer_callback_query(call.id)
        rows = _get_rows(
            db_connect,
            db_lock,
            "SELECT account_id FROM premium_favorites WHERE user_id=? ORDER BY created_at DESC",
            (call.from_user.id,),
        )
        if not rows:
            bot.send_message(
                call.message.chat.id,
                "❤️ <b>သိမ်းထားတဲ့အကောင့် မရှိသေးပါ။</b>\n\nကြိုက်တဲ့ Account မှာ <b>❤️ သိမ်းထားမယ်</b> ကိုနှိပ်ပြီး သိမ်းနိုင်ပါတယ်။",
                parse_mode="HTML",
                reply_markup=_build_feature_menu(),
            )
            return
        accounts = []
        for row in rows:
            acc = get_account_by_text_id(make_account_id(int(row["account_id"]))) if make_account_id else None
            if acc and acc.get("status") != "hidden":
                accounts.append(acc)
        if not accounts:
            bot.send_message(call.message.chat.id, "❤️ လောလောဆယ်ပြရန် သိမ်းထားတဲ့ Account မရှိပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[0]
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            "❤️ <b>သိမ်းထားတဲ့အကောင့်</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_account_buttons(acc),
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pf_fav_add_"))
    def pf_fav_add(call):
        bot.answer_callback_query(call.id, "သိမ်းပြီးပါပြီ ❤️")
        aid = call.data.replace("pf_fav_add_", "", 1)
        acc = get_account_by_text_id(aid)
        if not acc:
            bot.send_message(call.message.chat.id, "❌ ဒီအကောင့် မရှိတော့ပါ။")
            return
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO premium_favorites(user_id, account_id) VALUES(?,?)",
                    (call.from_user.id, acc["db_id"]),
                )
                conn.commit()
        log(call.from_user, "favorite_add", acc["id"])
        bot.send_message(
            call.message.chat.id,
            f"❤️ <b>{_safe_text(acc['id'])}</b> ကို သိမ်းထားပြီးပါပြီ။",
            parse_mode="HTML",
            reply_markup=_account_buttons(acc),
        )

    # ------------------------------------------------------------------
    # 👤 Profile / history
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_profile")
    def pf_profile(call):
        bot.answer_callback_query(call.id)
        fav = _get_one(db_connect, db_lock, "SELECT COUNT(*) n FROM premium_favorites WHERE user_id=?", (call.from_user.id,))["n"]
        viewed = _get_one(db_connect, db_lock, "SELECT COUNT(*) n FROM premium_views WHERE user_id=?", (call.from_user.id,))["n"]
        alert = _get_one(db_connect, db_lock, "SELECT * FROM premium_alerts WHERE user_id=?", (call.from_user.id,))
        username = f"@{call.from_user.username}" if call.from_user.username else "Username မရှိပါ"
        text = (
            "👤 <b>ကျွန်ုပ်၏အကောင့်</b>\n\n"
            f"👤 {html.escape(username)}\n"
            f"🆔 <code>{call.from_user.id}</code>\n\n"
            f"❤️ သိမ်းထားတာ — <b>{fav}</b> ခု\n"
            f"👀 ကြည့်ထားတာ — <b>{viewed}</b> ခု\n"
            f"🔔 အသိပေးချက် — <b>{'ဖွင့်ထားသည်' if _is_alert_enabled(alert) else 'ပိတ်ထားသည်'}</b>"
        )
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode="HTML",
            reply_markup=_menu(
                [
                    [("❤️ သိမ်းထားတဲ့အကောင့်များ", "pf_favorites")],
                    [("🕒 ကြည့်ထားခဲ့တဲ့အကောင့်များ", "pf_history")],
                    [("🔔 အသိပေးချက်စီမံမယ်", "pf_alerts")],
                    [("🔙 Feature Menu", "pf_menu")],
                ],
                row_width=1,
            ),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "pf_history")
    def pf_history(call):
        bot.answer_callback_query(call.id)
        rows = _get_rows(
            db_connect,
            db_lock,
            "SELECT account_id FROM premium_views WHERE user_id=? ORDER BY viewed_at DESC LIMIT 15",
            (call.from_user.id,),
        )
        accounts = []
        for row in rows:
            acc = get_account_by_text_id(make_account_id(int(row["account_id"]))) if make_account_id else None
            if acc and acc.get("status") != "hidden":
                accounts.append(acc)
        if not accounts:
            bot.send_message(call.message.chat.id, "🕒 ကြည့်ထားခဲ့တဲ့ Account မရှိသေးပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[0]
        bot.send_message(
            call.message.chat.id,
            "🕒 <b>မကြာသေးမီက ကြည့်ထားတဲ့အကောင့်</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_account_buttons(acc),
        )

    def _record_view(user_id: int, db_id: int):
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute(
                    "INSERT INTO premium_views(user_id,account_id,viewed_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id,account_id) DO UPDATE SET viewed_at=CURRENT_TIMESTAMP",
                    (user_id, db_id),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # 🆕 New accounts
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_new")
    def pf_new(call):
        bot.answer_callback_query(call.id)
        accounts = list(get_available_accounts())
        # main.py calculates is_new; fall back to newest order if absent.
        accounts.sort(key=lambda a: (not bool(a.get("is_new")), -int(a.get("db_id") or 0)))
        accounts = accounts[:20]
        if not accounts:
            bot.send_message(call.message.chat.id, "🆕 အသစ်တင်ထားတဲ့ Account မရှိသေးပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[0]
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            "🆕 <b>အသစ်တင်ထားတဲ့အကောင့်</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_next_list_keyboard(acc, accounts, "pf_new"),
        )

    def _next_list_keyboard(current, accounts, back_callback: str):
        idx = next((i for i, a in enumerate(accounts) if a["id"] == current["id"]), 0)
        next_idx = (idx + 1) % len(accounts)
        rows = []
        if current.get("status") == "available":
            rows.append([("⚡ အမြန်ဝယ်မယ်", f"pf_quick_{current['id']}")])
        rows.append([("❤️ သိမ်းထားမယ်", f"pf_fav_add_{current['id']}")])
        if len(accounts) > 1:
            rows.append([("➡️ နောက်အကောင့်ဆက်ကြည့်မယ်", f"pf_listnext_{back_callback}_{next_idx}")])
        rows.append([("🔙 Feature Menu", back_callback)])
        return _menu(rows, row_width=1)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pf_listnext_"))
    def pf_listnext(call):
        bot.answer_callback_query(call.id)
        _, _, rest = call.data.partition("pf_listnext_")
        # Back callback is encoded before the final index.
        try:
            back_cb, index_text = rest.rsplit("_", 1)
            idx = int(index_text)
        except Exception:
            back_cb, idx = "pf_new", 0
        if back_cb == "pf_new":
            accounts = list(get_available_accounts())
            accounts.sort(key=lambda a: (not bool(a.get("is_new")), -int(a.get("db_id") or 0)))
            accounts = accounts[:20]
        elif back_cb == "pf_flash":
            accounts = _flash_accounts()
        else:
            accounts = list(get_available_accounts())
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ Account မရှိပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[idx % len(accounts)]
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            _account_label(acc),
            parse_mode="HTML",
            reply_markup=_next_list_keyboard(acc, accounts, back_cb),
        )

    # ------------------------------------------------------------------
    # ⚡ Quick buy
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_quick_buy")
    def pf_quick_buy(call):
        bot.answer_callback_query(call.id)
        accounts = list(get_available_accounts())
        if not accounts:
            bot.send_message(call.message.chat.id, "⚡ လက်ရှိဝယ်လို့ရတဲ့ Account မရှိသေးပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[0]
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            "⚡ <b>အမြန်ဝယ်မယ်</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_menu(
                [
                    [("🛒 ဒီအကောင့် ဝယ်မယ်", f"buy_confirm_{acc['id']}")],
                    [("➡️ နောက်အကောင့်", f"pf_quicknext_0")],
                    [("🔙 Feature Menu", "pf_menu")],
                ],
                row_width=1,
            ),
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pf_quick_"))
    def pf_quick_account(call):
        bot.answer_callback_query(call.id)
        aid = call.data.replace("pf_quick_", "", 1)
        acc = get_account_by_text_id(aid)
        if not acc or acc.get("status") != "available":
            bot.send_message(call.message.chat.id, "❌ ဒီအကောင့်ကို လက်ရှိဝယ်လို့မရတော့ပါ။", reply_markup=_build_feature_menu())
            return
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            "⚡ <b>အမြန်ဝယ်မယ်</b>\n\n" + _account_label(acc) + "\n\n👆 ဝယ်မယ်ကိုနှိပ်ပြီး ဆက်လုပ်ပါ။",
            parse_mode="HTML",
            reply_markup=_menu(
                [
                    [("🛒 ဒီအကောင့် ဝယ်မယ်", f"buy_confirm_{acc['id']}")],
                    [("❤️ သိမ်းထားမယ်", f"pf_fav_add_{acc['id']}")],
                    [("🔙 Feature Menu", "pf_menu")],
                ],
                row_width=1,
            ),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "pf_quicknext_0")
    def pf_quicknext(call):
        bot.answer_callback_query(call.id)
        accounts = list(get_available_accounts())
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ Account မရှိပါ။", reply_markup=_build_feature_menu())
            return
        acc = accounts[0]
        bot.send_message(call.message.chat.id, _account_label(acc), parse_mode="HTML", reply_markup=_account_buttons(acc))

    # ------------------------------------------------------------------
    # 🔥 Flash Deal
    # ------------------------------------------------------------------
    def _flash_accounts():
        rows = _get_rows(
            db_connect,
            db_lock,
            """
            SELECT * FROM accounts
            WHERE status='available'
              AND flash_deal_price IS NOT NULL
              AND flash_deal_price > 0
              AND flash_deal_until IS NOT NULL
              AND flash_deal_until > CURRENT_TIMESTAMP
            ORDER BY flash_deal_until ASC, id ASC
            """,
        )
        result = []
        for row in rows:
            d = dict(row)
            d["id"] = f"ACC-{int(d['id']):03d}"
            d["effective_price"] = int(d.get("flash_deal_price") or d["price"])
            d["is_discounted"] = True
            d["is_verified"] = bool(d.get("is_verified"))
            d["photos"] = [x for x in str(d.get("photos") or "").split(",") if x]
            result.append(d)
        return result

    @bot.callback_query_handler(func=lambda c: c.data == "pf_flash")
    def pf_flash(call):
        bot.answer_callback_query(call.id)
        accounts = _flash_accounts()
        if not accounts:
            bot.send_message(
                call.message.chat.id,
                "🔥 <b>Flash Deal လက်ရှိမရှိသေးပါ။</b>\n\nAdmin က Flash Deal တင်ပေးတဲ့အချိန် ပြန်လာကြည့်နိုင်ပါတယ်။",
                parse_mode="HTML",
                reply_markup=_build_feature_menu(),
            )
            return
        acc = accounts[0]
        bot.send_message(
            call.message.chat.id,
            "🔥 <b>FLASH DEAL</b>\n\n" + _account_label(acc) + "\n\n⏰ သတ်မှတ်ထားတဲ့အချိန်အတွင်း ဝယ်ယူနိုင်ပါတယ်။",
            parse_mode="HTML",
            reply_markup=_next_list_keyboard(acc, accounts, "pf_flash"),
        )

    # ------------------------------------------------------------------
    # 🔎 Advanced search
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_advanced")
    def pf_advanced(call):
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "🔎 <b>အဆင့်မြင့်ရှာဖွေမယ်</b>\n\n"
            "ဒီလိုပုံစံနဲ့ ရိုက်ပေးပါ —\n"
            "<code>Gusion | 200000</code>\n\n"
            "Skin မသတ်မှတ်ချင်ရင် —\n"
            "<code>Any | 200000</code>",
            parse_mode="HTML",
            reply_markup=_menu([[('🔙 Feature Menu', 'pf_menu')]], row_width=1),
        )
        bot.register_next_step_handler(call.message, _receive_advanced_search)

    def _receive_advanced_search(message):
        raw = (message.text or "").strip()
        parts = [x.strip() for x in raw.split("|", 1)]
        if len(parts) != 2:
            m = re.match(r"^(.*?)\s+([0-9][0-9, ]*)\s*$", raw)
            if m:
                parts = [m.group(1).strip(), m.group(2).strip()]
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Format မမှန်ပါ။ <code>Gusion | 200000</code> လို့ ရိုက်ပေးပါ။", parse_mode="HTML")
            return
        skin = parts[0]
        if skin.lower() in ("any", "all", "အကုန်", "အားလုံး"):
            skin = ""
        try:
            budget = int(parts[1].replace(",", "").replace(" ", ""))
            if budget <= 0:
                raise ValueError
        except Exception:
            bot.send_message(message.chat.id, "❌ Budget မမှန်ပါ။")
            return
        accounts = list(get_available_accounts())
        terms = [t for t in skin.lower().split() if t]
        scored = []
        for acc in accounts:
            price = _price(acc)
            if price > budget:
                continue
            hay = f"{acc.get('title','')} {acc.get('skins','')}".lower()
            score = sum(1 for t in terms if t in hay)
            if not terms or score > 0:
                # Best match first, then lower price, then older ACC order.
                scored.append((score, -price, -int(acc.get("db_id") or 0), acc))
        scored.sort(reverse=True, key=lambda x: x[:3])
        results = [x[3] for x in scored][:20]
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute(
                    "INSERT INTO premium_recent_searches(user_id,skin_keyword,max_price,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET skin_keyword=excluded.skin_keyword,max_price=excluded.max_price,updated_at=excluded.updated_at",
                    (message.from_user.id, skin, budget, _now_iso()),
                )
                conn.commit()
        log(message.from_user, "premium_search", f"{skin}|{budget}")
        if not results:
            bot.send_message(message.chat.id, "❌ အနီးစပ်ဆုံး Account မတွေ့သေးပါ။", reply_markup=_build_feature_menu())
            return
        acc = results[0]
        _record_view(message.from_user.id, acc["db_id"])
        bot.send_message(
            message.chat.id,
            "🎯 <b>အနီးစပ်ဆုံး Account</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_search_nav_keyboard(results, 0),
        )

    def _search_nav_keyboard(results: list[dict[str, Any]], idx: int):
        acc = results[idx]
        rows = []
        if acc.get("status") == "available":
            rows.append([("⚡ အမြန်ဝယ်မယ်", f"pf_quick_{acc['id']}")])
        rows.append([("❤️ သိမ်းထားမယ်", f"pf_fav_add_{acc['id']}")])
        if len(results) > 1:
            prev_idx = (idx - 1) % len(results)
            next_idx = (idx + 1) % len(results)
            rows.append([("⬅️ အရင်အကောင့်", f"pf_search_nav_{prev_idx}"), ("➡️ နောက်အကောင့်", f"pf_search_nav_{next_idx}")])
        rows.append([("🔙 Feature Menu", "pf_menu")])
        # Store search result IDs in user's recent search table only; callback index resolves from same query.
        return _menu(rows, row_width=2)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pf_search_nav_"))
    def pf_search_nav(call):
        bot.answer_callback_query(call.id)
        row = _get_one(db_connect, db_lock, "SELECT skin_keyword,max_price FROM premium_recent_searches WHERE user_id=?", (call.from_user.id,))
        accounts = list(get_available_accounts())
        if row:
            skin = str(row["skin_keyword"] or "").lower().strip()
            budget = int(row["max_price"] or 0)
            terms = [t for t in skin.split() if t]
            scored = []
            for acc in accounts:
                if budget and _price(acc) > budget:
                    continue
                hay = f"{acc.get('title','')} {acc.get('skins','')}".lower()
                score = sum(1 for t in terms if t in hay)
                if not terms or score > 0:
                    scored.append((score, -_price(acc), -int(acc.get('db_id') or 0), acc))
            scored.sort(reverse=True, key=lambda x: x[:3])
            accounts = [x[3] for x in scored][:20]
        if not accounts:
            bot.send_message(call.message.chat.id, "❌ Search result မရှိတော့ပါ။", reply_markup=_build_feature_menu())
            return
        try:
            idx = int(call.data.replace("pf_search_nav_", "")) % len(accounts)
        except Exception:
            idx = 0
        acc = accounts[idx]
        _record_view(call.from_user.id, acc["db_id"])
        bot.send_message(
            call.message.chat.id,
            "🎯 <b>အနီးစပ်ဆုံး Account</b>\n\n" + _account_label(acc),
            parse_mode="HTML",
            reply_markup=_search_nav_keyboard(accounts, idx),
        )

    # ------------------------------------------------------------------
    # 🔔 Alerts: new accounts / price drops
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda c: c.data == "pf_alerts")
    def pf_alerts(call):
        bot.answer_callback_query(call.id)
        row = _get_one(db_connect, db_lock, "SELECT * FROM premium_alerts WHERE user_id=?", (call.from_user.id,))
        enabled = int(row["enabled"] or 0) if row else 0
        bot.send_message(
            call.message.chat.id,
            "🔔 <b>အသိပေးချက် စီမံမယ်</b>\n\n"
            "🆕 အသစ်တင် Account အသိပေးချက်\n"
            "💸 ဈေးကျသွားရင် အသိပေးချက်\n\n"
            f"လက်ရှိအခြေအနေ — <b>{'ဖွင့်ထားသည်' if enabled else 'ပိတ်ထားသည်'}</b>",
            parse_mode="HTML",
            reply_markup=_menu(
                [
                    [("✅ အသစ်တင် Account အသိပေးချက် ဖွင့်", "pf_alert_new_on")],
                    [("✅ ဈေးကျရင် အသိပေးချက် ဖွင့်", "pf_alert_drop_on")],
                    [("🔕 အသိပေးချက် ပိတ်မယ်", "pf_alert_off")],
                    [("🔙 Feature Menu", "pf_menu")],
                ],
                row_width=1,
            ),
        )

    def _set_alert(user_id: int, **updates):
        current = _get_one(db_connect, db_lock, "SELECT * FROM premium_alerts WHERE user_id=?", (user_id,))
        values = {
            "max_price": current["max_price"] if current else None,
            "skin_keyword": current["skin_keyword"] if current else "",
            "new_accounts": int(current["new_accounts"] or 0) if current else 0,
            "price_drops": int(current["price_drops"] or 0) if current else 0,
            "enabled": int(current["enabled"] or 0) if current else 0,
        }
        values.update(updates)
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute(
                    "INSERT INTO premium_alerts(user_id,max_price,skin_keyword,new_accounts,price_drops,enabled,updated_at) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET max_price=excluded.max_price,skin_keyword=excluded.skin_keyword,new_accounts=excluded.new_accounts,price_drops=excluded.price_drops,enabled=excluded.enabled,updated_at=excluded.updated_at",
                    (user_id, values["max_price"], values["skin_keyword"], values["new_accounts"], values["price_drops"], values["enabled"], _now_iso()),
                )
                conn.commit()

    @bot.callback_query_handler(func=lambda c: c.data in ("pf_alert_new_on", "pf_alert_drop_on", "pf_alert_off"))
    def pf_alert_toggle(call):
        bot.answer_callback_query(call.id)
        if call.data == "pf_alert_new_on":
            _set_alert(call.from_user.id, new_accounts=1, enabled=1)
            msg = "🆕 အသစ်တင် Account အသိပေးချက် ဖွင့်ပြီးပါပြီ။"
        elif call.data == "pf_alert_drop_on":
            _set_alert(call.from_user.id, price_drops=1, enabled=1)
            msg = "💸 ဈေးကျရင် အသိပေးချက် ဖွင့်ပြီးပါပြီ။"
        else:
            _set_alert(call.from_user.id, enabled=0)
            msg = "🔕 အသိပေးချက် ပိတ်ပြီးပါပြီ။"
        bot.send_message(call.message.chat.id, msg, reply_markup=_build_feature_menu())

    # ------------------------------------------------------------------
    # ✅ Verified / 🔔 Price Drop helper broadcasts for external code/admin
    # ------------------------------------------------------------------
    def set_verified(account_id: str, verified: bool = True) -> bool:
        acc = get_account_by_text_id(account_id)
        if not acc:
            return False
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute("UPDATE accounts SET is_verified=? WHERE id=?", (1 if verified else 0, acc["db_id"]))
                conn.commit()
        return True

    def set_flash_deal(account_id: str, deal_price: int, until_utc: str) -> bool:
        acc = get_account_by_text_id(account_id)
        if not acc or deal_price <= 0:
            return False
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute(
                    "UPDATE accounts SET flash_deal_price=?, flash_deal_until=? WHERE id=?",
                    (int(deal_price), until_utc, acc["db_id"]),
                )
                conn.commit()
        return True

    def clear_flash_deal(account_id: str) -> bool:
        acc = get_account_by_text_id(account_id)
        if not acc:
            return False
        with db_lock:
            with _connect(db_connect) as conn:
                conn.execute("UPDATE accounts SET flash_deal_price=NULL, flash_deal_until=NULL WHERE id=?", (acc["db_id"],))
                conn.commit()
        return True

    # Expose helpers on the module for launcher/admin integrations.
    install.set_verified = set_verified  # type: ignore[attr-defined]
    install.set_flash_deal = set_flash_deal  # type: ignore[attr-defined]
    install.clear_flash_deal = clear_flash_deal  # type: ignore[attr-defined]
    install.feature_menu = _build_feature_menu  # type: ignore[attr-defined]

    INSTALLED = True


__all__ = ["install", "INSTALLED"]
