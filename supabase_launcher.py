"""
EXTERNAL SUPABASE PERSISTENCE CONNECTOR
----------------------------------------
IMPORTANT:
- This file does NOT edit main.py.
- Keep the original main.py exactly as-is.
- Render Start Command:
      python supabase_launcher.py

What this external launcher adds:
1) Telegram photos -> Supabase Storage bucket: bot-images
2) Existing Telegram file_ids -> Supabase URL migration
3) SQLite shop.db -> private Supabase Storage bucket: bot-db-backups
4) Safe restore of shop.db when Render's local filesystem is empty
5) Empty local DB never overwrites a non-empty remote backup on startup
6) Webhook calls made by main.py during import are temporarily suppressed;
   the real webhook is configured once with 429 retry handling.
"""

import os
import time
import json
import sqlite3
import tempfile
import threading
import logging
import urllib.parse

import requests
import telebot

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
IMAGE_BUCKET = os.getenv("SUPABASE_IMAGE_BUCKET", "bot-images").strip()
DB_BACKUP_BUCKET = os.getenv("SUPABASE_DB_BUCKET", "bot-db-backups").strip()
DB_BACKUP_PATH = os.getenv("SUPABASE_DB_BACKUP_PATH", "shop.db").strip()
BACKUP_INTERVAL = max(5, int(os.getenv("SUPABASE_BACKUP_INTERVAL", "10")))
BACKUP_DELAY = max(2, int(os.getenv("SUPABASE_BACKUP_DELAY", "4")))
WEBHOOK_RETRIES = max(1, int(os.getenv("SUPABASE_WEBHOOK_RETRIES", "5")))

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SUPA_HEADERS = {
    "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
    "apikey": SUPABASE_SECRET_KEY,
}


def _public_url(bucket, path):
    return (
        f"{SUPABASE_URL}/storage/v1/object/public/"
        f"{urllib.parse.quote(bucket, safe='')}/"
        f"{urllib.parse.quote(path, safe='/') }"
    )


def _object_url(bucket, path):
    return (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"{urllib.parse.quote(bucket, safe='')}/"
        f"{urllib.parse.quote(path, safe='/') }"
    )


def _upload_object(bucket, path, data, content_type, cache_control=None):
    headers = dict(SUPA_HEADERS)
    headers.update({
        "Content-Type": content_type,
        "x-upsert": "true",
    })
    if cache_control:
        headers["Cache-Control"] = cache_control

    url = _object_url(bucket, path)
    last = None
    for method in ("POST", "PUT"):
        try:
            if method == "POST":
                r = requests.post(url, headers=headers, data=data, timeout=120)
            else:
                r = requests.put(url, headers=headers, data=data, timeout=120)
            if r.status_code in (200, 201, 204):
                return r
            last = r
        except requests.RequestException as exc:
            last = exc

    if isinstance(last, requests.Response):
        last.raise_for_status()
    raise RuntimeError(f"Supabase upload failed: {last}")


def _download_object(bucket, path):
    r = requests.get(
        _object_url(bucket, path),
        headers=SUPA_HEADERS,
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def ensure_db_backup_bucket():
    """Create the private DB bucket if it does not already exist."""
    try:
        r = requests.post(
            f"{SUPABASE_URL}/storage/v1/bucket",
            headers={**SUPA_HEADERS, "Content-Type": "application/json"},
            json={
                "id": DB_BACKUP_BUCKET,
                "name": DB_BACKUP_BUCKET,
                "public": False,
            },
            timeout=30,
        )
        if r.status_code in (200, 201, 204, 409):
            if r.status_code == 409:
                logging.info("Supabase private backup bucket already exists: %s", DB_BACKUP_BUCKET)
            else:
                logging.info("Supabase private backup bucket ready: %s", DB_BACKUP_BUCKET)
            return True
        logging.warning("Could not create backup bucket (%s): %s", r.status_code, r.text[:300])
    except requests.RequestException:
        logging.exception("Could not create/check DB backup bucket")
    return False


# ---------------------------------------------------------------------------
# Temporarily suppress main.py webhook calls DURING IMPORT ONLY.
# main.py remains unchanged on disk.
# ---------------------------------------------------------------------------
_original_remove_webhook = telebot.TeleBot.remove_webhook
_original_set_webhook = telebot.TeleBot.set_webhook


def _suppressed_remove_webhook(self, *args, **kwargs):
    logging.info("Webhook setup from main.py suppressed during external launcher import")
    return True


def _suppressed_set_webhook(self, *args, **kwargs):
    logging.info("Webhook set from main.py suppressed during external launcher import")
    return True


telebot.TeleBot.remove_webhook = _suppressed_remove_webhook
telebot.TeleBot.set_webhook = _suppressed_set_webhook

try:
    import main as original
finally:
    telebot.TeleBot.remove_webhook = _original_remove_webhook
    telebot.TeleBot.set_webhook = _original_set_webhook


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------
def account_count(db_path):
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            row = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()
            return int(row[0] or 0)
    except Exception:
        return 0


def create_consistent_db_copy(db_path):
    """Create a transactionally consistent SQLite copy using sqlite backup API."""
    fd, temp_path = tempfile.mkstemp(prefix="shop-backup-", suffix=".db")
    os.close(fd)

    src = None
    dst = None
    try:
        with original.db_lock:
            src = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
            dst = sqlite3.connect(temp_path, timeout=30, check_same_thread=False)
            src.backup(dst)
            dst.commit()
        return temp_path
    finally:
        if src is not None:
            src.close()
        if dst is not None:
            dst.close()


def validate_sqlite(path):
    with sqlite3.connect(path, timeout=30) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if str(integrity).lower() != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        return tables, (int(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]) if "accounts" in tables else 0)


def restore_remote_db_if_needed():
    """Restore only when the local DB has no accounts and remote has accounts."""
    db_path = original.DB_PATH
    local_accounts = account_count(db_path)

    try:
        remote_bytes = _download_object(DB_BACKUP_BUCKET, DB_BACKUP_PATH)
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 404:
            logging.info("No remote SQLite backup exists yet.")
        else:
            logging.exception("Could not read remote SQLite backup")
        return False
    except Exception:
        logging.exception("Could not download remote SQLite backup")
        return False

    fd, remote_path = tempfile.mkstemp(prefix="remote-shop-", suffix=".db")
    os.close(fd)
    try:
        with open(remote_path, "wb") as f:
            f.write(remote_bytes)

        _, remote_accounts = validate_sqlite(remote_path)
        logging.info(
            "Remote SQLite backup inspected: accounts=%s; local accounts=%s",
            remote_accounts,
            local_accounts,
        )

        if local_accounts > 0:
            return False

        if remote_accounts <= 0:
            logging.info("Remote backup is also empty; nothing to restore.")
            return False

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        tmp_restore = db_path + ".restore.tmp"

        # sqlite backup API gives a clean local DB copy.
        src = sqlite3.connect(remote_path, timeout=30)
        dst = sqlite3.connect(tmp_restore, timeout=30)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            src.close()
            dst.close()

        os.replace(tmp_restore, db_path)
        logging.info("SUPABASE_DB_RESTORE_OK accounts=%s path=%s", remote_accounts, db_path)
        return True
    finally:
        try:
            os.remove(remote_path)
        except OSError:
            pass


def backup_local_db(force=False):
    """Upload local SQLite DB, but never overwrite a good remote backup with an accidental empty DB."""
    db_path = original.DB_PATH
    if not os.path.exists(db_path):
        return False

    # Ensure the schema exists, without resetting anything.
    original.init_db()
    local_accounts = account_count(db_path)

    # A backup with accounts is the safest persisted source.
    # During normal operation, an intentional deletion from >0 to 0 is allowed
    # later by the monitor; at startup we do NOT overwrite a good remote DB with empty data.
    if local_accounts <= 0 and not force:
        logging.info("SUPABASE_DB_BACKUP_SKIP local accounts=0 (preserving remote backup)")
        return False

    temp_path = None
    try:
        temp_path = create_consistent_db_copy(db_path)
        _, copied_accounts = validate_sqlite(temp_path)
        if copied_accounts <= 0 and not force:
            logging.info("SUPABASE_DB_BACKUP_SKIP copied accounts=0")
            return False

        with open(temp_path, "rb") as f:
            data = f.read()

        _upload_object(
            DB_BACKUP_BUCKET,
            DB_BACKUP_PATH,
            data,
            "application/x-sqlite3",
            cache_control="no-store",
        )
        logging.info(
            "SUPABASE_DB_BACKUP_OK bucket=%s path=%s accounts=%s size=%s",
            DB_BACKUP_BUCKET,
            DB_BACKUP_PATH,
            copied_accounts,
            len(data),
        )
        return True
    except Exception:
        logging.exception("SUPABASE_DB_BACKUP_FAILED")
        return False
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Supabase image persistence
# ---------------------------------------------------------------------------
def supabase_public_url(path):
    return _public_url(IMAGE_BUCKET, path)


def upload_to_supabase(path, data, content_type="image/jpeg"):
    _upload_object(
        IMAGE_BUCKET,
        path,
        data,
        content_type,
        cache_control="31536000",
    )
    return supabase_public_url(path)


def telegram_photo_to_supabase(photo_size, chat_id, message_id):
    current = getattr(photo_size, "file_id", "") or ""
    if isinstance(current, str) and current.startswith(("http://", "https://")):
        return current

    file_info = original.bot.get_file(current)
    data = original.bot.download_file(file_info.file_path)
    unique = getattr(photo_size, "file_unique_id", None) or current
    path = f"telegram/{chat_id}/{message_id}_{unique}.jpg"
    return upload_to_supabase(path, data, "image/jpeg")


def migrate_existing_photos():
    """Migrate old Telegram file_ids in accounts/seller_requests to Supabase URLs."""
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
                    for idx, value in enumerate(old_values):
                        if value.startswith(("http://", "https://")):
                            new_values.append(value)
                            continue
                        try:
                            file_info = original.bot.get_file(value)
                            data = original.bot.download_file(file_info.file_path)
                            path = f"migrated/{table}/{row['id']}_{idx}.jpg"
                            new_values.append(upload_to_supabase(path, data, "image/jpeg"))
                            changed = True
                            logging.info("SUPABASE_MIGRATE_OK table=%s id=%s photo=%s", table, row["id"], idx + 1)
                        except Exception:
                            logging.exception(
                                "SUPABASE_MIGRATE_FAILED table=%s id=%s photo=%s",
                                table, row["id"], idx + 1,
                            )
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

        backup_local_db(force=False)
    except Exception:
        logging.exception("Existing photo migration failed")


def preprocess_update(update):
    """Persist incoming photos to Supabase before original handlers read file_id."""
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
                logging.info("SUPABASE_PHOTO_OK %s", public_url)
    except Exception:
        logging.exception("Supabase photo upload failed; preserving original Telegram file_id")
    return update


# ---------------------------------------------------------------------------
# Runtime patch: main.py remains untouched.
# ---------------------------------------------------------------------------
_original_process_new_updates = original.bot.process_new_updates


def _delayed_backup():
    try:
        backup_local_db(force=False)
    except Exception:
        logging.exception("Delayed DB backup failed")


def external_process_new_updates(updates):
    processed = [preprocess_update(u) for u in updates]
    result = _original_process_new_updates(processed)
    # TeleBot may dispatch handlers in worker threads, so wait a little before backing up.
    timer = threading.Timer(BACKUP_DELAY, _delayed_backup)
    timer.daemon = True
    timer.start()
    return result


original.bot.process_new_updates = external_process_new_updates


# ---------------------------------------------------------------------------
# Periodic persistence monitor
# ---------------------------------------------------------------------------
_monitor_stop = threading.Event()
_previous_accounts = account_count(original.DB_PATH)


def persistence_monitor():
    global _previous_accounts
    while not _monitor_stop.wait(BACKUP_INTERVAL):
        try:
            current = account_count(original.DB_PATH)

            # If current DB suddenly becomes empty from a non-empty runtime DB,
            # that is most likely a real admin deletion. Persist it so deleted
            # accounts stay deleted after restart.
            intentional_empty = _previous_accounts > 0 and current == 0

            if current > 0 or intentional_empty:
                backup_local_db(force=intentional_empty)

            _previous_accounts = current
        except Exception:
            logging.exception("Persistence monitor failed")


# ---------------------------------------------------------------------------
# Webhook: configure once, with 429 retry handling.
# ---------------------------------------------------------------------------
def configure_webhook_once():
    if not original.PUBLIC_URL:
        logging.warning("PUBLIC_URL မရှိပါ။ Render Environment Variable ထည့်ပါ။")
        return

    target = f"{original.PUBLIC_URL}/webhook/{original.TELEGRAM_TOKEN}"

    for attempt in range(1, WEBHOOK_RETRIES + 1):
        try:
            info = _original_set_webhook  # keep a reference for clarity
            # Call the real TeleBot method directly; main.py's import-time call was suppressed.
            existing = original.bot.get_webhook_info()
            existing_url = getattr(existing, "url", "") or ""
            if existing_url == target:
                logging.info("WEBHOOK_OK already correct; no update needed")
                return

            original.bot.set_webhook(
                url=target,
                drop_pending_updates=True,
            )
            logging.info("WEBHOOK_OK set: %s", target)
            return

        except Exception as exc:
            text = str(exc)
            retry_after = 2
            # telebot exception may expose result_json with retry_after.
            try:
                payload = getattr(exc, "result_json", None) or {}
                retry_after = int(payload.get("parameters", {}).get("retry_after", retry_after))
            except Exception:
                pass

            if "429" in text or "Too Many Requests" in text:
                wait = max(1, min(retry_after, 30))
                logging.warning("WEBHOOK_429 attempt=%s/%s retry_in=%ss", attempt, WEBHOOK_RETRIES, wait)
                time.sleep(wait)
                continue

            logging.exception("Webhook setup failed")
            return

    logging.error("WEBHOOK_FAILED after %s attempts", WEBHOOK_RETRIES)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def start_original_bot():
    ensure_db_backup_bucket()

    # main.py has already initialized the local schema during import.
    original.init_db()

    # Restore persistent DB BEFORE serving requests, when local DB is empty.
    restored = restore_remote_db_if_needed()
    if restored:
        original.init_db()

    # Migrate legacy Telegram photo ids after restore.
    threading.Thread(target=migrate_existing_photos, daemon=True).start()

    # The current DB is now the working DB. Start monitor and webhook.
    threading.Thread(target=persistence_monitor, daemon=True).start()
    configure_webhook_once()

    # One initial backup only when non-empty; never overwrite good remote data with empty startup DB.
    backup_local_db(force=False)

    port = int(os.getenv("PORT", "5000"))
    original.app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    start_original_bot()
