"""
EXTERNAL SUPABASE CONNECTOR - SAFE FINAL

IMPORTANT
- main.py is NOT edited by this file.
- Start Command: python supabase_launcher.py
- This launcher keeps the original bot flow and adds external persistence.

What this file does:
1. Prevents main.py startup code from repeatedly calling Telegram webhook APIs.
2. Uploads incoming Telegram photos to Supabase Storage (bot-images).
3. Keeps the original bot handlers unchanged.
4. Backs up the SQLite database to a PRIVATE Supabase Storage bucket.
5. Restores the database automatically when Render's local filesystem is empty.
6. Keeps old account data; it never deletes account rows.
7. Uses retries for Supabase and Telegram webhook calls.
"""

import io
import logging
import os
import sqlite3
import tempfile
import threading
import time
import urllib.parse
from contextlib import closing

import requests
import telebot

# ---------------------------------------------------------------------------
# Configuration from Render environment variables
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
IMAGE_BUCKET = os.getenv("SUPABASE_BUCKET", "bot-images").strip() or "bot-images"
BACKUP_BUCKET = os.getenv("SUPABASE_BACKUP_BUCKET", "bot-db-backups").strip() or "bot-db-backups"
BACKUP_PATH = os.getenv("SUPABASE_BACKUP_PATH", "shop.db").strip() or "shop.db"
SUPABASE_TIMEOUT = int(os.getenv("SUPABASE_REQUEST_TIMEOUT", "60"))
BACKUP_INTERVAL = int(os.getenv("SUPABASE_BACKUP_INTERVAL", "60"))

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ---------------------------------------------------------------------------
# IMPORTANT: block main.py webhook calls DURING IMPORT only.
# main.py currently sets/removes the webhook while it is imported. That caused
# the repeated 429 errors seen on Render. We do not edit main.py; we temporarily
# replace the class methods before importing it, then restore them afterwards.
# ---------------------------------------------------------------------------
_original_remove_webhook_method = telebot.TeleBot.remove_webhook
_original_set_webhook_method = telebot.TeleBot.set_webhook


def _blocked_remove_webhook(self, *args, **kwargs):
    logging.info("Startup webhook removal skipped by external launcher")
    return True


def _blocked_set_webhook(self, *args, **kwargs):
    logging.info("Startup webhook set skipped by external launcher")
    return True


telebot.TeleBot.remove_webhook = _blocked_remove_webhook
telebot.TeleBot.set_webhook = _blocked_set_webhook

try:
    import main as original
finally:
    # Restore the real TeleBot methods for all later runtime operations.
    telebot.TeleBot.remove_webhook = _original_remove_webhook_method
    telebot.TeleBot.set_webhook = _original_set_webhook_method


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _encoded_path(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def public_image_url(path: str) -> str:
    return (
        f"{SUPABASE_URL}/storage/v1/object/public/"
        f"{IMAGE_BUCKET}/{_encoded_path(path)}"
    )


def is_supabase_image_url(value) -> bool:
    return isinstance(value, str) and value.startswith(
        f"{SUPABASE_URL}/storage/v1/object/public/{IMAGE_BUCKET}/"
    )


def _storage_headers(content_type=None, upsert=False):
    headers = {
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "apikey": SUPABASE_SECRET_KEY,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if upsert:
        headers["x-upsert"] = "true"
        headers["Cache-Control"] = "31536000"
    return headers


def supabase_storage_request(method, url, **kwargs):
    last = None
    for attempt in range(1, 5):
        try:
            response = requests.request(method, url, timeout=SUPABASE_TIMEOUT, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504):
                return response
            last = RuntimeError(
                f"HTTP {response.status_code}: {response.text[:300]}"
            )
        except Exception as exc:
            last = exc
        time.sleep(min(2 ** (attempt - 1), 8))
    raise last or RuntimeError("Supabase request failed")


def ensure_backup_bucket():
    """Create the private DB backup bucket if it does not already exist."""
    url = f"{SUPABASE_URL}/storage/v1/bucket"
    payload = {
        "id": BACKUP_BUCKET,
        "name": BACKUP_BUCKET,
        "public": False,
        "file_size_limit": 50 * 1024 * 1024,
    }
    try:
        response = supabase_storage_request(
            "POST",
            url,
            headers={
                **_storage_headers("application/json"),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code in (200, 201):
            logging.info("Supabase private backup bucket ready: %s", BACKUP_BUCKET)
            return True
        # 409 normally means the bucket already exists.
        if response.status_code == 409 or "already exists" in response.text.lower():
            logging.info("Supabase private backup bucket already exists: %s", BACKUP_BUCKET)
            return True
        logging.error(
            "Could not create backup bucket: HTTP %s %s",
            response.status_code,
            response.text[:500],
        )
    except Exception:
        logging.exception("Backup bucket setup failed")
    return False


def upload_to_supabase(path, data, content_type="image/jpeg"):
    url = f"{SUPABASE_URL}/storage/v1/object/{IMAGE_BUCKET}/{_encoded_path(path)}"
    response = supabase_storage_request(
        "POST",
        url,
        headers=_storage_headers(content_type, upsert=True),
        data=data,
    )
    if response.status_code not in (200, 201, 204):
        # PUT fallback for installations where POST replacement differs.
        response = supabase_storage_request(
            "PUT",
            url,
            headers=_storage_headers(content_type, upsert=True),
            data=data,
        )
    response.raise_for_status()
    return public_image_url(path)


def download_supabase_object(path_or_url):
    if is_supabase_image_url(path_or_url):
        url = path_or_url
    else:
        url = f"{SUPABASE_URL}/storage/v1/object/{IMAGE_BUCKET}/{_encoded_path(path_or_url)}"
    response = supabase_storage_request(
        "GET",
        url,
        headers=_storage_headers(),
    )
    response.raise_for_status()
    return response.content


# ---------------------------------------------------------------------------
# Photo persistence
# ---------------------------------------------------------------------------

def telegram_photo_to_supabase(photo_size, chat_id, message_id):
    file_info = original.bot.get_file(photo_size.file_id)
    data = original.bot.download_file(file_info.file_path)
    unique = getattr(photo_size, "file_unique_id", None) or photo_size.file_id
    path = f"telegram/{chat_id}/{message_id}_{unique}.jpg"
    return upload_to_supabase(path, data, "image/jpeg")


def preprocess_update(update):
    """Upload incoming photos before the untouched original handlers process them."""
    try:
        message = getattr(update, "message", None)
        if message and getattr(message, "photo", None):
            photos = message.photo
            if photos:
                public_url = telegram_photo_to_supabase(
                    photos[-1],
                    message.chat.id,
                    message.message_id,
                )
                photos[-1].file_id = public_url
                logging.info("SUPABASE_UPLOAD_OK %s", public_url)
    except Exception:
        logging.exception("SUPABASE_UPLOAD_FAILED; keeping original Telegram file_id")
    return update


# ---------------------------------------------------------------------------
# SQLite -> Supabase persistent backup
# ---------------------------------------------------------------------------
backup_lock = threading.Lock()
backup_timer = None
backup_ready = False


def _database_path():
    return getattr(original, "DB_PATH", os.getenv("DB_PATH", "/var/data/shop.db"))


def local_account_count():
    try:
        with original.db_lock:
            with closing(original.db_connect()) as conn:
                row = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
                return int(row["n"] or 0)
    except Exception:
        return 0


def create_sqlite_snapshot():
    """Use SQLite's online backup API for a consistent snapshot."""
    source_path = _database_path()
    if not os.path.exists(source_path):
        return None

    fd, snapshot_path = tempfile.mkstemp(prefix="shop_backup_", suffix=".db")
    os.close(fd)
    try:
        with original.db_lock:
            with closing(original.db_connect()) as source:
                with sqlite3.connect(snapshot_path) as target:
                    source.backup(target)
                    target.commit()
        return snapshot_path
    except Exception:
        try:
            os.remove(snapshot_path)
        except OSError:
            pass
        raise


def backup_database_now():
    global backup_ready
    if not backup_lock.acquire(blocking=False):
        return False
    snapshot_path = None
    try:
        if not ensure_backup_bucket():
            return False
        snapshot_path = create_sqlite_snapshot()
        if not snapshot_path:
            logging.warning("No local SQLite database found to back up")
            return False

        with open(snapshot_path, "rb") as handle:
            data = handle.read()

        url = f"{SUPABASE_URL}/storage/v1/object/{BACKUP_BUCKET}/{_encoded_path(BACKUP_PATH)}"
        response = supabase_storage_request(
            "POST",
            url,
            headers=_storage_headers("application/x-sqlite3", upsert=True),
            data=data,
        )
        if response.status_code not in (200, 201, 204):
            response = supabase_storage_request(
                "PUT",
                url,
                headers=_storage_headers("application/x-sqlite3", upsert=True),
                data=data,
            )
        response.raise_for_status()
        backup_ready = True
        logging.info(
            "SUPABASE_DB_BACKUP_OK bucket=%s path=%s accounts=%s size=%s",
            BACKUP_BUCKET,
            BACKUP_PATH,
            local_account_count(),
            len(data),
        )
        return True
    except Exception:
        logging.exception("SUPABASE_DB_BACKUP_FAILED")
        return False
    finally:
        if snapshot_path:
            try:
                os.remove(snapshot_path)
            except OSError:
                pass
        backup_lock.release()


def download_database_backup():
    url = f"{SUPABASE_URL}/storage/v1/object/{BACKUP_BUCKET}/{_encoded_path(BACKUP_PATH)}"
    response = supabase_storage_request(
        "GET",
        url,
        headers=_storage_headers(),
    )
    response.raise_for_status()
    return response.content


def restore_database_if_empty():
    """Restore only when local SQLite has no accounts, so existing data is never overwritten."""
    if local_account_count() > 0:
        logging.info("LOCAL_DB_HAS_DATA accounts=%s; restore skipped", local_account_count())
        return False

    try:
        data = download_database_backup()
    except Exception:
        logging.info("No Supabase database backup available yet; keeping current local DB")
        return False

    if not data:
        logging.warning("Supabase database backup is empty; restore skipped")
        return False

    db_path = _database_path()
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix="restore_", suffix=".db", dir=directory or None)
    os.close(fd)
    try:
        with open(temp_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with original.db_lock:
            # Close connections first by simply replacing the file after all handlers
            # are idle. Startup is the only restore point, so this is safe here.
            os.replace(temp_path, db_path)
        original.init_db()
        logging.info(
            "SUPABASE_DB_RESTORE_OK accounts=%s size=%s",
            local_account_count(),
            len(data),
        )
        return True
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def schedule_backup(delay=5):
    global backup_timer
    with backup_lock:
        if backup_timer is not None and backup_timer.is_alive():
            return
        backup_timer = threading.Timer(delay, backup_database_now)
        backup_timer.daemon = True
        backup_timer.start()


def periodic_backup_loop():
    while True:
        time.sleep(max(BACKUP_INTERVAL, 30))
        try:
            backup_database_now()
        except Exception:
            logging.exception("Periodic database backup failed")


# ---------------------------------------------------------------------------
# Telegram webhook helper (only sets it when it is actually wrong)
# ---------------------------------------------------------------------------

def telegram_api_url(method):
    return f"https://api.telegram.org/bot{original.TELEGRAM_TOKEN}/{method}"


def ensure_webhook_once():
    if not getattr(original, "PUBLIC_URL", ""):
        logging.warning("PUBLIC_URL မရှိပါ။ Render Environment Variable ထည့်ပါ။")
        return

    desired = f"{original.PUBLIC_URL}/webhook/{original.TELEGRAM_TOKEN}"
    try:
        info = requests.get(
            telegram_api_url("getWebhookInfo"),
            timeout=30,
        )
        if info.status_code == 429:
            retry_after = 1
            try:
                retry_after = int(info.json().get("parameters", {}).get("retry_after", 1))
            except Exception:
                pass
            logging.warning("Telegram webhook rate limited; retrying after %ss", retry_after)
            time.sleep(min(max(retry_after, 1), 10))
            info = requests.get(telegram_api_url("getWebhookInfo"), timeout=30)

        info.raise_for_status()
        current = info.json().get("result", {}).get("url", "")

        if current == desired:
            logging.info("WEBHOOK_OK already correct; no update needed")
            return

        for attempt in range(1, 6):
            response = requests.post(
                telegram_api_url("setWebhook"),
                json={"url": desired, "drop_pending_updates": True},
                timeout=30,
            )
            if response.status_code == 200:
                logging.info("WEBHOOK_OK set: %s/webhook/...", original.PUBLIC_URL)
                return
            if response.status_code == 429:
                retry_after = 1
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", 1))
                except Exception:
                    pass
                logging.warning(
                    "Telegram webhook 429 attempt=%s; retrying after %ss",
                    attempt,
                    retry_after,
                )
                time.sleep(min(max(retry_after, 1), 10))
                continue
            logging.error(
                "Telegram setWebhook failed HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            return
    except Exception:
        logging.exception("Webhook verification/setup failed")


# ---------------------------------------------------------------------------
# Runtime wrappers
# ---------------------------------------------------------------------------
_original_process_new_updates = original.bot.process_new_updates


def external_process_new_updates(updates):
    processed = [preprocess_update(u) for u in updates]
    result = _original_process_new_updates(processed)
    # Back up after successful processing. This preserves account writes made
    # by the untouched original handlers without changing their source.
    schedule_backup(3)
    return result


original.bot.process_new_updates = external_process_new_updates


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def start_original_bot():
    global backup_ready

    original.init_db()

    # Restore only if Render has no local account records.
    restore_database_if_empty()

    # Ensure Supabase backup bucket exists and seed a backup from any existing DB.
    ensure_backup_bucket()
    if local_account_count() > 0:
        backup_database_now()

    threading.Thread(target=periodic_backup_loop, daemon=True).start()

    # Main webhook setup was suppressed during import; set/check it exactly once here.
    ensure_webhook_once()

    port = int(os.getenv("PORT", "5000"))
    logging.info("STARTING_ORIGINAL_FLASK port=%s", port)
    original.app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    start_original_bot()
