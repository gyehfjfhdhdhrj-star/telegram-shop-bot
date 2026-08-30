"""
MLBB MARKET - Gmail OAuth 2.0 Connector (stable signed-state)

Separate Gmail connector for the existing Telegram bot.
Does not modify main.py or supabase_launcher.py.

Safe scope:
- Administrator-authorized Gmail OAuth connection
- Gmail mailbox metadata
- Recent message metadata (From/To/Subject/Date)

This module does not extract, store, or forward OTP / verification codes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Optional

from flask import Blueprint, make_response, redirect, request
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRET_FILE = os.getenv(
    "GOOGLE_OAUTH_CLIENT_SECRET_FILE",
    "/etc/secrets/client_secret.json",
).strip()
CALLBACK_PATH = (
    os.getenv(
        "GOOGLE_OAUTH_CALLBACK_PATH",
        "/gmail/oauth/callback",
    ).strip()
    or "/gmail/oauth/callback"
)
DB_PATH = (
    os.getenv("DB_PATH", "/tmp/shop.db").strip()
    or "/tmp/shop.db"
)
TOKEN_DIR = Path(
    os.getenv(
        "GOOGLE_OAUTH_TOKEN_DIR",
        "/tmp/gmail_tokens",
    ).strip()
    or "/tmp/gmail_tokens"
)

# A signed, self-contained state avoids relying on in-memory state or a
# state table that can be affected by the DB backup/restore cycle.
STATE_SECRET = (
    os.getenv("GOOGLE_OAUTH_STATE_SECRET", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)
STATE_TTL_SECONDS = 600

bp = Blueprint("gmail_oauth", __name__)


def _connect_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    with closing(_connect_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                token_path TEXT NOT NULL,
                token_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'available',
                moonton_status TEXT NOT NULL DEFAULT 'not_changed',
                assigned_account TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Existing Render/Supabase-restored DBs may predate token_json.
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(gmail_mailboxes)"
            ).fetchall()
        }
        if "token_json" not in columns:
            conn.execute(
                "ALTER TABLE gmail_mailboxes "
                "ADD COLUMN token_json TEXT NOT NULL DEFAULT ''"
            )

        conn.commit()


def _redirect_uri(public_url: str) -> str:
    return public_url.rstrip("/") + CALLBACK_PATH


def _flow(
    public_url: str,
    state: Optional[str] = None,
    code_verifier: Optional[str] = None,
) -> Flow:
    client_path = Path(CLIENT_SECRET_FILE)

    if not client_path.is_file():
        raise FileNotFoundError(
            "Google OAuth client secret file not found: "
            f"{CLIENT_SECRET_FILE}"
        )

    flow = Flow.from_client_secrets_file(
        str(client_path),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(public_url),
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )

    if state:
        flow.state = state

    return flow


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(
        value + ("=" * (-len(value) % 4))
    )


def _signature(payload: str) -> str:
    if not STATE_SECRET:
        raise RuntimeError(
            "GOOGLE_OAUTH_STATE_SECRET or TELEGRAM_BOT_TOKEN is missing"
        )
    return _b64e(
        hmac.new(
            STATE_SECRET.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )


def _make_state(admin_id: int) -> str:
    payload = {
        "v": 1,
        "admin_id": int(admin_id),
        "iat": int(time.time()),
        "nonce": uuid.uuid4().hex,
    }
    encoded = _b64e(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    return f"{encoded}.{_signature(encoded)}"


def _verify_state(state: str, expected_admin_id: int) -> bool:
    try:
        encoded, supplied_signature = state.split(".", 1)
        expected_signature = _signature(encoded)

        if not hmac.compare_digest(
            supplied_signature,
            expected_signature,
        ):
            return False

        payload = json.loads(
            _b64d(encoded).decode("utf-8")
        )

        issued_at = int(payload.get("iat", 0))
        admin_id = int(payload.get("admin_id", 0))

        if admin_id != int(expected_admin_id):
            return False

        age = int(time.time()) - issued_at
        return 0 <= age <= STATE_TTL_SECONDS
    except Exception:
        return False


def create_authorization_url(
    public_url: str,
    owner_user_id: int,
) -> tuple[str, str, str]:
    init_db()

    state = _make_state(owner_user_id)

    # PKCE verifier must survive until the OAuth callback. Keep it in a
    # short-lived HttpOnly browser cookie rather than putting it into the
    # OAuth state value or the database.
    code_verifier = secrets.token_urlsafe(64)

    flow = _flow(
        public_url,
        state=state,
        code_verifier=code_verifier,
    )

    authorization_url, returned_state = flow.authorization_url(
        state=state,
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    if returned_state != state:
        raise RuntimeError(
            "OAuth state mismatch while creating authorization URL."
        )

    return authorization_url, state, code_verifier


def _safe_token_path(email: str) -> Path:
    safe = "".join(
        ch
        for ch in email.lower()
        if ch.isalnum() or ch in "._-"
    )
    return TOKEN_DIR / f"{safe}.json"


def save_credentials(
    creds: Credentials,
    email: str,
):
    init_db()
    path = _safe_token_path(email)

    token_json = creds.to_json()

    # Keep a local copy for immediate use, but the DB copy is the
    # persistent source because shop.db is already backed up/restored.
    path.write_text(
        token_json,
        encoding="utf-8",
    )

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    with closing(_connect_db()) as conn:
        conn.execute(
            """
            INSERT INTO gmail_mailboxes(
                email,
                token_path,
                token_json,
                status,
                updated_at
            )
            VALUES(?, ?, ?, 'available', CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                token_path=excluded.token_path,
                token_json=excluded.token_json,
                status='available',
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                email,
                str(path),
                token_json,
            ),
        )
        conn.commit()


def load_credentials(
    email: str,
) -> Optional[Credentials]:
    init_db()

    with closing(_connect_db()) as conn:
        row = conn.execute(
            """
            SELECT token_path, token_json
            FROM gmail_mailboxes
            WHERE email=?
            """,
            (email,),
        ).fetchone()

    if not row:
        return None

    creds = None
    token_json = (row["token_json"] or "").strip()

    # Prefer the persistent DB copy after Render restart/redeploy.
    if token_json:
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(token_json),
                SCOPES,
            )
        except Exception:
            logging.exception(
                "GMAIL_TOKEN_DB_LOAD_FAILED email=%s",
                email,
            )
            creds = None

    # Backward-compatible fallback for an older local token file.
    if creds is None:
        path = Path(row["token_path"])
        if path.is_file():
            creds = Credentials.from_authorized_user_file(
                str(path),
                SCOPES,
            )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds, email)

    return creds


def mailbox_service(email: str):
    creds = load_credentials(email)

    if not creds or not creds.valid:
        raise RuntimeError(
            "Gmail OAuth authorization missing/expired for "
            f"{email}"
        )

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def mailbox_profile(email: str) -> dict:
    return (
        mailbox_service(email)
        .users()
        .getProfile(userId="me")
        .execute()
    )


def list_recent_messages(
    email: str,
    query: str = "",
    max_results: int = 10,
) -> list[dict]:
    service = mailbox_service(email)
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max_results,
        )
        .execute()
    )
    return response.get("messages", [])


def get_message_headers(
    email: str,
    message_id: str,
) -> dict:
    service = mailbox_service(email)
    message = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=[
                "From",
                "To",
                "Subject",
                "Date",
            ],
        )
        .execute()
    )

    headers = {}
    for header in (
        message
        .get("payload", {})
        .get("headers", [])
    ):
        name = header.get("name", "")
        value = header.get("value", "")
        if name in {
            "From",
            "To",
            "Subject",
            "Date",
        }:
            headers[name] = value

    return {
        "id": message_id,
        "headers": headers,
        "labelIds": message.get(
            "labelIds",
            [],
        ),
    }


@bp.route("/gmail/oauth/start")
def oauth_start():
    public_url = os.getenv(
        "PUBLIC_URL",
        "",
    ).strip()

    raw_admin = request.args.get(
        "admin_id",
        "0",
    ).strip()

    try:
        admin_id = int(raw_admin)
        configured_admin = int(
            os.getenv(
                "ADMIN_ID",
                "0",
            ).strip()
        )
    except ValueError:
        return (
            "OAuth configuration error: ADMIN_ID must be numeric.",
            500,
        )

    if not public_url or admin_id <= 0:
        return (
            "OAuth configuration is missing: PUBLIC_URL/admin_id.",
            400,
        )

    if admin_id != configured_admin:
        return "Forbidden", 403

    try:
        url, state, code_verifier = create_authorization_url(
            public_url,
            admin_id,
        )

        response = redirect(url)

        response.set_cookie(
            "gmail_oauth_state",
            state,
            max_age=600,
            secure=True,
            httponly=True,
            samesite="Lax",
        )

        response.set_cookie(
            "gmail_oauth_code_verifier",
            code_verifier,
            max_age=600,
            secure=True,
            httponly=True,
            samesite="Lax",
        )

        logging.info(
            "GMAIL_OAUTH_START_OK admin_id=%s state_len=%s verifier_len=%s",
            admin_id,
            len(state),
            len(code_verifier),
        )

        return response

    except Exception as exc:
        logging.exception(
            "GMAIL_OAUTH_START_FAILED"
        )
        return (
            "Gmail OAuth start failed. "
            f"Reason: {str(exc)[:500]}",
            500,
        )


@bp.route(CALLBACK_PATH)
def oauth_callback():
    state = request.args.get(
        "state",
        "",
    ).strip()

    try:
        configured_admin = int(
            os.getenv(
                "ADMIN_ID",
                "0",
            ).strip()
        )
    except ValueError:
        return (
            "OAuth configuration error: ADMIN_ID is invalid.",
            500,
        )

    if not state:
        logging.error(
            "GMAIL_OAUTH_CALLBACK_MISSING_STATE"
        )
        return "Missing OAuth state.", 400

    if not _verify_state(
        state,
        configured_admin,
    ):
        logging.error(
            "GMAIL_OAUTH_STATE_INVALID"
        )
        return (
            "Invalid or expired OAuth state. "
            "Please start Gmail connection again from Telegram.",
            400,
        )

    if request.args.get("error"):
        error = request.args.get(
            "error",
            "access_denied",
        )
        logging.warning(
            "GMAIL_OAUTH_USER_DENIED error=%s",
            error,
        )
        return (
            "Google authorization was cancelled or denied. "
            "Please return to Telegram and try again.",
            400,
        )

    public_url = os.getenv(
        "PUBLIC_URL",
        "",
    ).strip()

    code_verifier = request.cookies.get(
        "gmail_oauth_code_verifier",
        "",
    ).strip()

    if not code_verifier:
        logging.error(
            "GMAIL_OAUTH_CODE_VERIFIER_MISSING"
        )
        return (
            "Gmail OAuth session expired. "
            "Please start Gmail connection again from Telegram.",
            400,
        )

    try:
        flow = _flow(
            public_url,
            state=state,
            code_verifier=code_verifier,
        )

        logging.info(
            "GMAIL_OAUTH_CALLBACK_TOKEN_EXCHANGE_START public_url=%s callback_path=%s",
            public_url,
            CALLBACK_PATH,
        )

        # Render terminates TLS at its edge proxy. Flask may therefore
        # see request.url as http://... internally even though the public
        # callback is https://.... oauthlib rejects that as insecure.
        # Rebuild the callback URL from the public HTTPS origin instead.
        query_string = request.query_string.decode(
            "utf-8",
            errors="replace",
        )
        callback_url = (
            public_url.rstrip("/")
            + CALLBACK_PATH
        )
        if query_string:
            callback_url += "?" + query_string

        flow.fetch_token(
            authorization_response=callback_url
        )

        service = build(
            "gmail",
            "v1",
            credentials=flow.credentials,
            cache_discovery=False,
        )

        profile = (
            service.users()
            .getProfile(userId="me")
            .execute()
        )

        email = (
            profile
            .get(
                "emailAddress",
                "",
            )
            .strip()
            .lower()
        )

        if not email:
            return (
                "Could not identify Gmail mailbox.",
                400,
            )

        save_credentials(
            flow.credentials,
            email,
        )

        logging.info(
            "GMAIL_OAUTH_CALLBACK_OK email=%s",
            email,
        )

        response = make_response(
            "Gmail connected successfully. "
            "You may close this page and return to Telegram."
        )
        response.delete_cookie(
            "gmail_oauth_state",
        )
        response.delete_cookie(
            "gmail_oauth_code_verifier",
        )
        return response

    except Exception as exc:
        logging.exception(
            "GMAIL_OAUTH_CALLBACK_FAILED"
        )
        return (
            "Gmail OAuth callback failed. "
            f"Reason: {str(exc)[:500]}",
            500,
        )


def register_flask(app):
    init_db()

    endpoints = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
    }

    if "gmail_oauth.oauth_start" not in endpoints:
        app.register_blueprint(bp)
