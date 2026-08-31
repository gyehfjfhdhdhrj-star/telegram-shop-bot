"""Separate Gmail OAuth admin integration for MLBB MARKET.
Does not modify main.py or supabase_launcher.py.
Does not extract/store/forward OTP codes.
"""
from __future__ import annotations
import logging, os
from contextlib import closing
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import gmail_oauth

_INSTALLED = False

def install(original):
    global _INSTALLED
    if _INSTALLED:
        return
    bot = original.bot
    admin_id = int(original.ADMIN_ID)
    gmail_oauth.DB_PATH = getattr(original, "DB_PATH", gmail_oauth.DB_PATH)
    gmail_oauth.init_db()

    endpoints = {rule.endpoint for rule in original.app.url_map.iter_rules()}
    if "gmail_oauth.oauth_start" not in endpoints:
        original.app.register_blueprint(gmail_oauth.bp)

    def gmail_menu():
        m = InlineKeyboardMarkup(row_width=1)
        m.add(InlineKeyboardButton("➕ Gmail ချိတ်မယ်", callback_data="gmail_admin_connect"))
        m.add(InlineKeyboardButton("📋 Gmail စာရင်း", callback_data="gmail_admin_list"))
        m.add(InlineKeyboardButton("♻️ Gmail Available ပြန်လုပ်မယ်", callback_data="gmail_admin_reset_menu"))
        m.add(InlineKeyboardButton("📨 Mail စစ်မယ်", callback_data="gmail_admin_check"))
        m.add(InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"))
        return m

    def mailbox_rows():
        with closing(gmail_oauth._connect_db()) as conn:
            return conn.execute("""
                SELECT id,email,status,moonton_status,assigned_account,updated_at
                FROM gmail_mailboxes ORDER BY id DESC
            """).fetchall()

    def oauth_url():
        public_url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
        return f"{public_url}/gmail/oauth/start?admin_id={admin_id}" if public_url else None

    def show_reset_menu(chat_id):
        all_rows = mailbox_rows()
        if not all_rows:
            bot.send_message(
                chat_id,
                "📧 Gmail record မရှိသေးပါ။",
                reply_markup=gmail_menu(),
            )
            return

        m = InlineKeyboardMarkup(row_width=1)
        for r in all_rows[:50]:
            status = str(r["status"] or "-")
            moonton = str(r["moonton_status"] or "-")
            m.add(
                InlineKeyboardButton(
                    f"♻️ GMAIL-{int(r['id']):03d} — {r['email']} "
                    f"({status}/{moonton})",
                    callback_data=f"gmail_admin_reset_{int(r['id'])}",
                )
            )

        m.add(
            InlineKeyboardButton(
                "🔙 Gmail Menu",
                callback_data="gmail_admin_menu",
            )
        )

        bot.send_message(
            chat_id,
            "♻️ <b>Gmail Available ပြန်လုပ်မယ်</b>\n\n"
            "စမ်းသပ်ပြီး Pending / Assigned ဖြစ်နေတဲ့ Gmail ကို ရွေးပါ။\n"
            "Gmail record ကို မဖျက်ဘဲ <b>Available</b> အဖြစ် ပြန်ထားပေးပါမယ်။",
            parse_mode="HTML",
            reply_markup=m,
        )

    def reset_mailbox(mailbox_id):
        with closing(gmail_oauth._connect_db()) as conn:
            row = conn.execute(
                """
                SELECT id,email,status,moonton_status,assigned_account
                FROM gmail_mailboxes
                WHERE id=?
                """,
                (int(mailbox_id),),
            ).fetchone()

            if not row:
                return None

            conn.execute(
                """
                UPDATE gmail_mailboxes
                SET status='available',
                    moonton_status='not_changed',
                    assigned_account='',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (int(mailbox_id),),
            )
            conn.commit()

            return {
                "id": int(row["id"]),
                "email": str(row["email"]),
                "old_status": str(row["status"] or "-"),
                "old_moonton": str(row["moonton_status"] or "-"),
                "old_assigned": str(row["assigned_account"] or "-"),
            }

    def show_mailboxes(chat_id):
        rows = mailbox_rows()
        if not rows:
            bot.send_message(chat_id, "📧 <b>Gmail စာရင်း</b>\n\nချိတ်ထားတဲ့ Gmail မရှိသေးပါ။", parse_mode="HTML", reply_markup=gmail_menu())
            return
        status_map = {"available":"🟢 Available","assigned":"🟡 Assigned","pending":"⏳ Pending","completed":"✅ Completed"}
        moonton_map = {"not_changed":"❌ မပြောင်းရသေး","pending":"⏳ Pending","changed":"✅ ပြောင်းပြီး"}
        lines = ["📧 <b>Gmail စာရင်း</b>\n"]
        k = InlineKeyboardMarkup(row_width=1)
        for r in rows[:30]:
            rid = int(r["id"])
            lines.append(
                f"<b>GMAIL-{rid:03d}</b>\n"
                f"📧 {r['email']}\n"
                f"📌 Status — {status_map.get(r['status'], r['status'])}\n"
                f"🎮 Moonton — {moonton_map.get(r['moonton_status'], r['moonton_status'])}\n"
                f"🆔 Account — {r['assigned_account'] or '-'}\n"
            )
            k.add(InlineKeyboardButton(f"📨 {r['email']}", callback_data=f"gmail_admin_mail_{rid}"))
        k.add(InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_home"))
        bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML", reply_markup=k)

    def show_recent(chat_id, mailbox_id):
        with closing(gmail_oauth._connect_db()) as conn:
            r = conn.execute("SELECT email FROM gmail_mailboxes WHERE id=?", (int(mailbox_id),)).fetchone()
        if not r:
            bot.send_message(chat_id, "❌ Gmail မတွေ့ပါ။", reply_markup=gmail_menu())
            return
        email = r["email"]
        try:
            ids = gmail_oauth.list_recent_messages(email, query="newer_than:7d", max_results=10)
            lines = [f"📨 <b>{email}</b>\n"]
            if not ids:
                lines.append("လွန်ခဲ့တဲ့ ၇ ရက်အတွင်း mail အသစ် မတွေ့ပါ။")
            for item in ids:
                meta = gmail_oauth.get_message_headers(email, item["id"])
                h = meta.get("headers", {})
                lines.append(f"• <b>From:</b> {h.get('From','-')}\n  <b>Subject:</b> {h.get('Subject','-')}\n  <b>Date:</b> {h.get('Date','-')}\n")
            bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML", reply_markup=gmail_menu())
        except Exception as exc:
            logging.exception("Gmail metadata check failed")
            bot.send_message(chat_id, f"❌ Gmail စစ်ဆေးရာမှာ အမှားရှိပါတယ်။\n<code>{str(exc)[:200]}</code>", parse_mode="HTML", reply_markup=gmail_menu())

    if not hasattr(original, "_gmail_previous_admin_keyboard"):
        original._gmail_previous_admin_keyboard = original.admin_keyboard

    def admin_keyboard_with_gmail():
        m = original._gmail_previous_admin_keyboard()
        if not any(getattr(b, "callback_data", None) == "gmail_admin_menu" for row in m.keyboard for b in row):
            m.add(InlineKeyboardButton("📧 Gmail စီမံမယ်", callback_data="gmail_admin_menu"))
        return m
    original.admin_keyboard = admin_keyboard_with_gmail

    previous_process = bot.process_new_updates
    def intercepted(updates):
        remaining = []
        for update in updates or []:
            call = getattr(update, "callback_query", None)
            if call is None or not (call.data or "").startswith("gmail_admin_"):
                remaining.append(update); continue
            if call.from_user.id != admin_id:
                try: bot.answer_callback_query(call.id, "Admin သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
                except Exception: pass
                continue
            try: bot.answer_callback_query(call.id)
            except Exception: pass
            data = call.data or ""
            if data == "gmail_admin_menu":
                bot.send_message(
                    call.message.chat.id,
                    "📧 <b>Gmail စီမံမယ်</b>",
                    parse_mode="HTML",
                    reply_markup=gmail_menu(),
                )

            elif data == "gmail_admin_reset_menu":
                show_reset_menu(call.message.chat.id)

            elif data.startswith("gmail_admin_reset_"):
                try:
                    mailbox_id = int(
                        data.replace("gmail_admin_reset_", "", 1)
                    )
                except ValueError:
                    bot.send_message(
                        admin_id,
                        "❌ Gmail ID မမှန်ပါ။",
                        reply_markup=gmail_menu(),
                    )
                else:
                    result = reset_mailbox(mailbox_id)
                    if not result:
                        bot.send_message(
                            admin_id,
                            "❌ Gmail မတွေ့ပါ။",
                            reply_markup=gmail_menu(),
                        )
                    else:
                        bot.send_message(
                            admin_id,
                            "✅ Gmail ကို <b>Available</b> ပြန်လုပ်ပြီးပါပြီ။\n\n"
                            f"📧 {result['email']}\n"
                            f"အရင် Status — {result['old_status']}\n"
                            f"အရင် Moonton — {result['old_moonton']}\n"
                            f"အရင် Assigned — {result['old_assigned']}\n\n"
                            "ဒီ Gmail ကို နောက်ထပ် Seller အတွက် ပြန်အသုံးပြုနိုင်ပါပြီ။",
                            parse_mode="HTML",
                            reply_markup=gmail_menu(),
                        )

            elif data == "gmail_admin_connect":
                url = oauth_url()
                if not url:
                    bot.send_message(admin_id, "❌ PUBLIC_URL မရှိသေးပါ။", reply_markup=gmail_menu())
                else:
                    k = InlineKeyboardMarkup(row_width=1)
                    k.add(InlineKeyboardButton("🔐 Google နဲ့ Gmail ချိတ်မယ်", url=url))
                    k.add(InlineKeyboardButton("🏠 Gmail Menu", callback_data="gmail_admin_menu"))
                    bot.send_message(admin_id, "🔐 <b>Gmail OAuth</b>\n\nချိတ်မယ့် Google Account ကိုရွေးပြီး Access ခွင့်ပြုပါ။", parse_mode="HTML", reply_markup=k)
            elif data == "gmail_admin_list":
                show_mailboxes(call.message.chat.id)
            elif data == "gmail_admin_check":
                rows = mailbox_rows()
                if rows: show_recent(call.message.chat.id, int(rows[0]["id"]))
                else: bot.send_message(admin_id, "📧 Gmail ချိတ်ထားတာ မရှိသေးပါ။", reply_markup=gmail_menu())
            elif data.startswith("gmail_admin_mail_"):
                try: show_recent(call.message.chat.id, int(data.replace("gmail_admin_mail_", "", 1)))
                except ValueError: bot.send_message(admin_id, "❌ Gmail ID မမှန်ပါ။", reply_markup=gmail_menu())
        if remaining: return previous_process(remaining)
        return None
    bot.process_new_updates = intercepted
    _INSTALLED = True
