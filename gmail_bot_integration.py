"""Separate Gmail OAuth admin integration for MLBB MARKET.
Does not modify main.py or supabase_launcher.py.
Does not extract/store/forward OTP codes.
"""

from __future__ import annotations

import html
import logging
import os
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

    gmail_oauth.DB_PATH = getattr(
        original,
        "DB_PATH",
        gmail_oauth.DB_PATH,
    )
    gmail_oauth.init_db()

    endpoints = {
        rule.endpoint
        for rule in original.app.url_map.iter_rules()
    }
    if "gmail_oauth.oauth_start" not in endpoints:
        original.app.register_blueprint(
            gmail_oauth.bp
        )

    def esc(value) -> str:
        """Escape dynamic text before putting it inside HTML."""
        return html.escape(
            "" if value is None else str(value),
            quote=False,
        )

    def gmail_menu():
        m = InlineKeyboardMarkup(row_width=1)
        m.add(
            InlineKeyboardButton(
                "➕ Gmail ချိတ်မယ်",
                callback_data="gmail_admin_connect",
            )
        )
        m.add(
            InlineKeyboardButton(
                "📋 Gmail စာရင်း",
                callback_data="gmail_admin_list",
            )
        )
        m.add(
            InlineKeyboardButton(
                "📨 Mail စစ်မယ်",
                callback_data="gmail_admin_check",
            )
        )
        m.add(
            InlineKeyboardButton(
                "🏠 Admin Menu",
                callback_data="admin_home",
            )
        )
        return m

    def mailbox_rows():
        with closing(
            gmail_oauth._connect_db()
        ) as conn:
            return conn.execute(
                """
                SELECT
                    id,
                    email,
                    status,
                    moonton_status,
                    assigned_account,
                    updated_at
                FROM gmail_mailboxes
                ORDER BY id DESC
                """
            ).fetchall()

    def oauth_url():
        public_url = (
            os.getenv("PUBLIC_URL", "")
            .strip()
            .rstrip("/")
        )
        if not public_url:
            return None

        return (
            f"{public_url}"
            f"/gmail/oauth/start?admin_id={admin_id}"
        )

    def show_mailboxes(chat_id):
        rows = mailbox_rows()

        if not rows:
            bot.send_message(
                chat_id,
                "📧 <b>Gmail စာရင်း</b>\n\n"
                "ချိတ်ထားတဲ့ Gmail မရှိသေးပါ။",
                parse_mode="HTML",
                reply_markup=gmail_menu(),
            )
            return

        status_map = {
            "available": "🟢 Available",
            "assigned": "🟡 Assigned",
            "pending": "⏳ Pending",
            "completed": "✅ Completed",
        }

        moonton_map = {
            "not_changed": "❌ မပြောင်းရသေး",
            "pending": "⏳ Pending",
            "changed": "✅ ပြောင်းပြီး",
        }

        lines = [
            "📧 <b>Gmail စာရင်း</b>\n"
        ]
        k = InlineKeyboardMarkup(row_width=1)

        for row in rows[:30]:
            rid = int(row["id"])
            email_value = esc(row["email"])
            status_value = esc(
                status_map.get(
                    row["status"],
                    row["status"],
                )
            )
            moonton_value = esc(
                moonton_map.get(
                    row["moonton_status"],
                    row["moonton_status"],
                )
            )
            account_value = esc(
                row["assigned_account"] or "-"
            )

            lines.append(
                f"<b>GMAIL-{rid:03d}</b>\n"
                f"📧 {email_value}\n"
                f"📌 Status — {status_value}\n"
                f"🎮 Moonton — {moonton_value}\n"
                f"🆔 Account — {account_value}\n"
            )

            # Button text is plain text; Telegram still accepts it safely,
            # but escape it consistently for unusual mailbox names.
            k.add(
                InlineKeyboardButton(
                    f"📨 {row['email']}",
                    callback_data=(
                        f"gmail_admin_mail_{rid}"
                    ),
                )
            )

        k.add(
            InlineKeyboardButton(
                "🏠 Admin Menu",
                callback_data="admin_home",
            )
        )

        bot.send_message(
            chat_id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=k,
        )

    def show_recent(chat_id, mailbox_id):
        with closing(
            gmail_oauth._connect_db()
        ) as conn:
            row = conn.execute(
                """
                SELECT email
                FROM gmail_mailboxes
                WHERE id=?
                """,
                (int(mailbox_id),),
            ).fetchone()

        if not row:
            bot.send_message(
                chat_id,
                "❌ Gmail မတွေ့ပါ။",
                reply_markup=gmail_menu(),
            )
            return

        email_raw = row["email"]
        email_value = esc(email_raw)

        try:
            ids = gmail_oauth.list_recent_messages(
                email_raw,
                query="newer_than:7d",
                max_results=10,
            )

            lines = [
                f"📨 <b>{email_value}</b>\n"
            ]

            if not ids:
                lines.append(
                    "လွန်ခဲ့တဲ့ ၇ ရက်အတွင်း "
                    "mail အသစ် မတွေ့ပါ။"
                )

            for item in ids:
                meta = (
                    gmail_oauth.get_message_headers(
                        email_raw,
                        item["id"],
                    )
                )
                headers = meta.get(
                    "headers",
                    {},
                )

                sender = esc(
                    headers.get(
                        "From",
                        "-",
                    )
                )
                subject = esc(
                    headers.get(
                        "Subject",
                        "-",
                    )
                )
                date_value = esc(
                    headers.get(
                        "Date",
                        "-",
                    )
                )

                lines.append(
                    f"• <b>From:</b> {sender}\n"
                    f"  <b>Subject:</b> {subject}\n"
                    f"  <b>Date:</b> {date_value}\n"
                )

            bot.send_message(
                chat_id,
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=gmail_menu(),
            )

        except Exception as exc:
            logging.exception(
                "Gmail metadata check failed"
            )

            safe_error = esc(
                str(exc)[:200]
            )

            bot.send_message(
                chat_id,
                "❌ Gmail စစ်ဆေးရာမှာ "
                "အမှားရှိပါတယ်။\n"
                f"<code>{safe_error}</code>",
                parse_mode="HTML",
                reply_markup=gmail_menu(),
            )

    # Preserve the existing admin menu.
    if not hasattr(
        original,
        "_gmail_previous_admin_keyboard",
    ):
        original._gmail_previous_admin_keyboard = (
            original.admin_keyboard
        )

    def admin_keyboard_with_gmail():
        m = (
            original._gmail_previous_admin_keyboard()
        )

        if not any(
            getattr(
                button,
                "callback_data",
                None,
            ) == "gmail_admin_menu"
            for row in m.keyboard
            for button in row
        ):
            m.add(
                InlineKeyboardButton(
                    "📧 Gmail စီမံမယ်",
                    callback_data="gmail_admin_menu",
                )
            )

        return m

    original.admin_keyboard = (
        admin_keyboard_with_gmail
    )

    previous_process = (
        bot.process_new_updates
    )

    def intercepted(updates):
        remaining = []

        for update in updates or []:
            call = getattr(
                update,
                "callback_query",
                None,
            )

            if (
                call is None
                or not (
                    call.data or ""
                ).startswith("gmail_admin_")
            ):
                remaining.append(update)
                continue

            if call.from_user.id != admin_id:
                try:
                    bot.answer_callback_query(
                        call.id,
                        "Admin သာ အသုံးပြုနိုင်ပါတယ်။",
                        show_alert=True,
                    )
                except Exception:
                    pass
                continue

            try:
                bot.answer_callback_query(
                    call.id
                )
            except Exception:
                pass

            data = call.data or ""

            if data == "gmail_admin_menu":
                bot.send_message(
                    call.message.chat.id,
                    "📧 <b>Gmail စီမံမယ်</b>",
                    parse_mode="HTML",
                    reply_markup=gmail_menu(),
                )

            elif data == "gmail_admin_connect":
                url = oauth_url()

                if not url:
                    bot.send_message(
                        admin_id,
                        "❌ PUBLIC_URL မရှိသေးပါ။",
                        reply_markup=gmail_menu(),
                    )
                else:
                    k = InlineKeyboardMarkup(
                        row_width=1
                    )
                    k.add(
                        InlineKeyboardButton(
                            "🔐 Google နဲ့ Gmail ချိတ်မယ်",
                            url=url,
                        )
                    )
                    k.add(
                        InlineKeyboardButton(
                            "🏠 Gmail Menu",
                            callback_data="gmail_admin_menu",
                        )
                    )

                    bot.send_message(
                        admin_id,
                        "🔐 <b>Gmail OAuth</b>\n\n"
                        "ချိတ်မယ့် Google Account ကိုရွေးပြီး "
                        "Access ခွင့်ပြုပါ။",
                        parse_mode="HTML",
                        reply_markup=k,
                    )

            elif data == "gmail_admin_list":
                show_mailboxes(
                    call.message.chat.id
                )

            elif data == "gmail_admin_check":
                rows = mailbox_rows()

                if rows:
                    show_recent(
                        call.message.chat.id,
                        int(rows[0]["id"]),
                    )
                else:
                    bot.send_message(
                        admin_id,
                        "📧 Gmail ချိတ်ထားတာ "
                        "မရှိသေးပါ။",
                        reply_markup=gmail_menu(),
                    )

            elif data.startswith(
                "gmail_admin_mail_"
            ):
                try:
                    mailbox_id = int(
                        data.replace(
                            "gmail_admin_mail_",
                            "",
                            1,
                        )
                    )
                    show_recent(
                        call.message.chat.id,
                        mailbox_id,
                    )
                except ValueError:
                    bot.send_message(
                        admin_id,
                        "❌ Gmail ID မမှန်ပါ။",
                        reply_markup=gmail_menu(),
                    )

        if remaining:
            return previous_process(
                remaining
            )

        return None

    bot.process_new_updates = intercepted
    _INSTALLED = True
