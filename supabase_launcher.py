"""
EXTERNAL SUPABASE CONNECTOR - STORAGE SAFE DISPLAY VERSION
===========================================================

IMPORTANT:
- This file does NOT edit main.py.
- Keep the original main.py exactly as supplied by the user.
- Render Start Command:
      python supabase_launcher.py

What this launcher does externally:
1. Uploads incoming Telegram photos to Supabase Storage bucket `bot-images`.
2. Stores the resulting permanent Supabase public URL in the ORIGINAL bot state/DB
   by replacing only the incoming photo file_id at runtime. main.py source is untouched.
3. When the ORIGINAL bot later tries to send a Supabase URL back to Telegram,
   this launcher downloads the object and sends it to Telegram as a real uploaded
   photo/file. This avoids relying on Telegram fetching the Supabase URL itself.
4. Migrates old Telegram file_ids already stored in SQLite to Supabase.
5. DOES NOT call remove_webhook()/set_webhook(); main.py keeps responsibility for
   the webhook setup, preventing the previous 429 webhook loop.
"""

import copy
import io
import logging
import os
import threading
import time
import urllib.parse

import requests

# Keep the original bot source completely untouched.
import main as original


SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "bot-images").strip() or "bot-images"
REQUEST_TIMEOUT = int(os.getenv("SUPABASE_REQUEST_TIMEOUT", "60"))

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ---------------------------------------------------------------------------
# SUPABASE STORAGE HELPERS
# ---------------------------------------------------------------------------

def supabase_public_url(path: str) -> str:
    return (
        f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
        f"{urllib.parse.quote(path, safe='/')}"
    )


def is_supabase_url(value) -> bool:
    return isinstance(value, str) and value.startswith(
        f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
    )


def upload_to_supabase(path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Upload one object to the existing public bucket, with PUT fallback."""
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{encoded_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": content_type,
        "Cache-Control": "31536000",
        "x-upsert": "true",
    }

    last_error = None
    for method in ("post", "put"):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code in (200, 201, 204):
                return supabase_public_url(path)
            last_error = RuntimeError(
                f"Supabase {method.upper()} upload failed: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
        except Exception as exc:
            last_error = exc

    raise last_error or RuntimeError("Unknown Supabase upload error")


def download_supabase_object(value: str) -> bytes:
    """Download a public Supabase Storage object as bytes for Telegram upload."""
    response = requests.get(value, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def telegram_photo_to_supabase(photo_size, chat_id, message_id) -> str:
    """Download a Telegram photo and store it permanently in Supabase."""
    file_info = original.bot.get_file(photo_size.file_id)
    data = original.bot.download_file(file_info.file_path)
    unique = getattr(photo_size, "file_unique_id", None) or photo_size.file_id
    path = f"telegram/{chat_id}/{message_id}_{unique}.jpg"
    public_url = upload_to_supabase(path, data, "image/jpeg")
    logging.info("SUPABASE_UPLOAD_OK path=%s", path)
    return public_url


# ---------------------------------------------------------------------------
# INCOMING PHOTO INTERCEPTOR
# ---------------------------------------------------------------------------

def preprocess_update(update):
    """
    Upload incoming photos before original handlers process them.

    Telegram sends an album as separate photo messages. Each message is handled
    independently and keeps its own original message_id/file_unique_id, so the
    original photo order is preserved.
    """
    try:
        message = getattr(update, "message", None)
        photos = getattr(message, "photo", None) if message else None
        if message and photos:
            source = photos[-1]
            if not is_supabase_url(getattr(source, "file_id", None)):
                public_url = telegram_photo_to_supabase(
                    source,
                    message.chat.id,
                    message.message_id,
                )
                # IMPORTANT: this is an in-memory runtime change only.
                # main.py on disk is not modified.
                source.file_id = public_url
                logging.info(
                    "PHOTO_REFERENCE_REPLACED chat=%s message=%s",
                    message.chat.id,
                    message.message_id,
                )
    except Exception:
        # Storage failure must never kill the original bot flow.
        logging.exception("SUPABASE_INCOMING_UPLOAD_FAILED; keeping Telegram file_id")
    return update


# ---------------------------------------------------------------------------
# OUTGOING PHOTO INTERCEPTOR
# ---------------------------------------------------------------------------
# Save original methods before monkey-patching them.
_original_process_new_updates = original.bot.process_new_updates
_original_send_photo = original.bot.send_photo
_original_send_media_group = original.bot.send_media_group


def _media_value(media):
    return getattr(media, "media", media)


def _supabase_bytesio(url: str) -> io.BytesIO:
    data = download_supabase_object(url)
    stream = io.BytesIO(data)
    stream.name = "image.jpg"
    stream.seek(0)
    return stream


def _prepare_media_item(item):
    """Return a copy of InputMediaPhoto with Supabase URL replaced by a file object."""
    value = _media_value(item)
    if not is_supabase_url(value):
        return item

    prepared = copy.copy(item)
    stream = _supabase_bytesio(value)
    prepared.media = stream
    return prepared


def external_send_photo(chat_id, photo, *args, **kwargs):
    """
    If the original bot tries to send a Supabase public URL, download it and
    upload the bytes to Telegram. Normal Telegram file_ids/URLs are unchanged.
    """
    try:
        if is_supabase_url(photo):
            logging.info("SUPABASE_DOWNLOAD_FOR_TELEGRAM_OK url=%s", photo)
            stream = _supabase_bytesio(photo)
            return _original_send_photo(chat_id, stream, *args, **kwargs)
    except Exception:
        logging.exception("SUPABASE_SEND_PHOTO_FAILED; trying original photo value")
    return _original_send_photo(chat_id, photo, *args, **kwargs)


def external_send_media_group(chat_id, media, *args, **kwargs):
    """Convert Supabase URLs inside InputMediaPhoto items into file uploads."""
    try:
        prepared_media = [_prepare_media_item(item) for item in media]
        return _original_send_media_group(chat_id, prepared_media, *args, **kwargs)
    except Exception:
        logging.exception("SUPABASE_SEND_MEDIA_GROUP_FAILED; trying original media")
        return _original_send_media_group(chat_id, media, *args, **kwargs)


# The original Flask webhook calls this method internally.
def external_process_new_updates(updates):
    processed = [preprocess_update(u) for u in updates]
    return _original_process_new_updates(processed)


# Runtime-only monkey patches. main.py source remains unchanged.
original.bot.process_new_updates = external_process_new_updates
original.bot.send_photo = external_send_photo
original.bot.send_media_group = external_send_media_group


# ---------------------------------------------------------------------------
# EXISTING PHOTO MIGRATION
# ---------------------------------------------------------------------------

def migrate_existing_photos():
    """Move existing Telegram file_ids in accounts/seller_requests to Supabase."""
    logging.info("PHOTO_MIGRATION_START")
    migrated = 0
    failed = 0

    try:
        original.init_db()

        for table in ("accounts", "seller_requests"):
            try:
                with original.db_lock:
                    with original.closing(original.db_connect()) as conn:
                        rows = conn.execute(
                            f"SELECT id, photos FROM {table} "
                            "WHERE photos IS NOT NULL AND photos != ''"
                        ).fetchall()

                for row in rows:
                    old_values = [x.strip() for x in (row["photos"] or "").split(",") if x.strip()]
                    if not old_values:
                        continue

                    new_values = []
                    changed = False

                    for index, value in enumerate(old_values):
                        # Already permanent: keep exactly as stored.
                        if value.startswith("http://") or value.startswith("https://"):
                            new_values.append(value)
                            continue

                        try:
                            file_info = original.bot.get_file(value)
                            data = original.bot.download_file(file_info.file_path)
                            path = f"migrated/{table}/{row['id']}/{index + 1}.jpg"
                            new_url = upload_to_supabase(path, data, "image/jpeg")
                            new_values.append(new_url)
                            changed = True
                            migrated += 1
                        except Exception:
                            failed += 1
                            logging.exception(
                                "PHOTO_MIGRATION_ITEM_FAILED table=%s id=%s index=%s",
                                table,
                                row["id"],
                                index + 1,
                            )
                            # Keep original value if migration fails.
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
                failed += 1
                logging.exception("PHOTO_MIGRATION_TABLE_FAILED table=%s", table)

    except Exception:
        logging.exception("PHOTO_MIGRATION_FAILED")

    logging.info("PHOTO_MIGRATION_DONE migrated=%s failed=%s", migrated, failed)


# ---------------------------------------------------------------------------
# STARTUP
# ---------------------------------------------------------------------------

def start_original_bot():
    """
    Start the original Flask app without touching its webhook configuration.

    main.py already performs its original init_db() and webhook setup at import
    time. We deliberately do NOT call remove_webhook()/set_webhook() here.
    """
    try:
        # Give the original module a chance to finish its startup setup first.
        original.init_db()
    except Exception:
        logging.exception("Original init_db() failed")

    # Run migration in the background. This never blocks the web server.
    threading.Thread(target=migrate_existing_photos, daemon=True, name="supabase-photo-migration").start()

    port = int(os.getenv("PORT", "5000"))
    logging.info("SUPABASE_CONNECTOR_READY bucket=%s", BUCKET)
    logging.info("STARTING_ORIGINAL_FLASK port=%s", port)
    original.app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    start_original_bot()
