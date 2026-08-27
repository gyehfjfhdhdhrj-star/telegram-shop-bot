"""
EXTERNAL SUPABASE CONNECTOR
---------------------------
This file does NOT modify main.py.
Keep the original 2298-line bot code exactly as it is.

Render Start Command:
    python supabase_launcher.py

main.py must be the original bot file.
"""

import os
import logging
import threading
import urllib.parse
import requests

# Import the original bot as a module. Its 2298 lines are not edited.
import main as original

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
BUCKET = "bot-images"

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")


def supabase_public_url(path):
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


def upload_to_supabase(path, data, content_type="image/jpeg"):
    """Upload/overwrite one file in the existing public bot-images bucket."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path, safe='/')}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": content_type,
        "x-upsert": "true",
        "Cache-Control": "31536000",
    }
    r = requests.post(url, headers=headers, data=data, timeout=60)
    if r.status_code not in (200, 201):
        # Some Supabase Storage versions prefer PUT for object replacement.
        r = requests.put(url, headers=headers, data=data, timeout=60)
    r.raise_for_status()
    return supabase_public_url(path)


def telegram_photo_to_supabase(photo_size, chat_id, message_id):
    """Download the Telegram photo once, then return a permanent Supabase URL."""
    file_info = original.bot.get_file(photo_size.file_id)
    data = original.bot.download_file(file_info.file_path)
    unique = getattr(photo_size, "file_unique_id", None) or photo_size.file_id
    path = f"telegram/{chat_id}/{message_id}_{unique}.jpg"
    return upload_to_supabase(path, data, "image/jpeg")


def preprocess_update(update):
    """Replace incoming photo file_ids with Supabase public URLs before the
    original 2298-line handlers see the update.

    This means the original receive_photo_message() function stays untouched.
    """
    try:
        message = getattr(update, "message", None)
        if message and getattr(message, "photo", None):
            photos = message.photo
            if photos:
                # Upload the highest-resolution Telegram photo.
                public_url = telegram_photo_to_supabase(
                    photos[-1],
                    message.chat.id,
                    message.message_id,
                )
                # The original code reads message.photo[-1].file_id.
                photos[-1].file_id = public_url
                logging.info("Photo moved to Supabase: %s", public_url)
    except Exception:
        # Never break the original bot if storage temporarily fails.
        # Leave the Telegram file_id untouched so the original flow can continue.
        logging.exception("Supabase photo upload failed; keeping Telegram file_id")
    return update


# Keep the original process_new_updates implementation available.
_original_process_new_updates = original.bot.process_new_updates


def external_process_new_updates(updates):
    processed = [preprocess_update(u) for u in updates]
    return _original_process_new_updates(processed)


# The original Flask webhook calls bot.process_new_updates().
# Replace only this runtime method; main.py itself is NOT edited.
original.bot.process_new_updates = external_process_new_updates


def migrate_existing_photos():
    """Best-effort migration of existing Telegram file_ids in SQLite.

    Existing account/seller-request records are copied to Supabase and their
    stored photo values are changed only in the database, not in main.py.
    Already-migrated http(s) URLs are skipped.
    """
    try:
        original.init_db()
        tables = ["accounts", "seller_requests"]
        for table in tables:
            try:
                with original.db_lock:
                    with original.closing(original.db_connect()) as conn:
                        rows = conn.execute(f"SELECT id, photos FROM {table} WHERE photos IS NOT NULL AND photos != ''").fetchall()

                for row in rows:
                    old_values = [x for x in (row["photos"] or "").split(",") if x]
                    if not old_values:
                        continue
                    new_values = []
                    changed = False
                    for idx, value in enumerate(old_values):
                        value = value.strip()
                        if not value or value.startswith("http://") or value.startswith("https://"):
                            new_values.append(value)
                            continue
                        try:
                            file_info = original.bot.get_file(value)
                            data = original.bot.download_file(file_info.file_path)
                            path = f"migrated/{table}/{row['id']}_{idx}.jpg"
                            new_values.append(upload_to_supabase(path, data, "image/jpeg"))
                            changed = True
                        except Exception:
                            logging.exception("Could not migrate %s id=%s photo=%s", table, row["id"], idx + 1)
                            # Keep the old Telegram file_id if one item fails.
                            new_values.append(value)

                    if changed:
                        with original.db_lock:
                            with original.closing(original.db_connect()) as conn:
                                conn.execute(
                                    f"UPDATE {table} SET photos=? WHERE id=?",
                                    (",".join(new_values), row["id"]),
                                )
                                conn.commit()
            except Exception:
                logging.exception("Photo migration failed for table %s", table)
    except Exception:
        logging.exception("Existing photo migration failed")


def start_original_bot():
    # Do NOT touch Telegram webhook here.
    # main.py already configures the webhook when it is imported.
    # Re-setting/removing it here causes Telegram 429 Too Many Requests.
    original.init_db()
    logging.info("Using webhook configured by main.py; launcher will not reset it.")

    # Migrate old Telegram file_ids in a background thread so startup is not blocked.
    threading.Thread(target=migrate_existing_photos, daemon=True).start()

    port = int(os.getenv("PORT", "5000"))
    original.app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    start_original_bot()
