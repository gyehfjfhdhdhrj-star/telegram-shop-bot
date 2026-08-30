"""
MLBB MARKET - Gmail OAuth 2.0 Connector (SAFE)

Purpose:
- Connect administrator-owned Gmail mailboxes through Google's OAuth 2.0 flow.
- Store OAuth tokens in a local SQLite table so the existing Supabase DB backup
  mechanism can persist them.
- Check mailbox/message metadata and detect incoming mail without exposing or
  forwarding authentication codes.

This module intentionally does NOT extract, store, or forward OTP/verification
codes.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Blueprint, redirect, request, session
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRET_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "client_secret.json")
CALLBACK_PATH = os.getenv("GOOGLE_OAUTH_CALLBACK_PATH", "/gmail/oauth/callback")
DB_PATH = os.getenv("DB_PATH", "/var/data/shop.db")
TOKEN_DIR = Path(os.getenv("GOOGLE_OAUTH_TOKEN_DIR", "/var/data/gmail_tokens"))

_lock = threading.Lock()
_state = {}

bp = Blueprint("gmail_oauth", __name__)


def _connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, closing(_connect_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_oauth_states (
                state TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                token_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                moonton_status TEXT NOT NULL DEFAULT 'not_changed',
                assigned_account TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def _redirect_uri(public_url: str) -> str:
    return public_url.rstrip("/") + CALLBACK_PATH


def _flow(public_url: str, state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=_redirect_uri(public_url),
    )
    if state:
        flow.state = state
    return flow


def create_authorization_url(public_url: str, owner_user_id: int) -> str:
    init_db()
    state = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc).isoformat()

    with _lock, closing(_connect_db()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO gmail_oauth_states(
                state,
                owner_user_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                state,
                int(owner_user_id),
                created_at,
            ),
        )
        conn.commit()
    flow = _flow(public_url, state=state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def _safe_token_path(email: str) -> Path:
    safe = "".join(ch for ch in email.lower() if ch.isalnum() or ch in "._-")
    return TOKEN_DIR / f"{safe}.json"


def save_credentials(creds: Credentials, email: str):
    path = _safe_token_path(email)
    path.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    with _lock, closing(_connect_db()) as conn:
        conn.execute(
            """
            INSERT INTO gmail_mailboxes(email, token_path, status, updated_at)
            VALUES (?, ?, 'available', CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                token_path=excluded.token_path,
                updated_at=CURRENT_TIMESTAMP
            """,
            (email, str(path)),
        )
        conn.commit()


def load_credentials(email: str) -> Optional[Credentials]:
    init_db()
    with closing(_connect_db()) as conn:
        row = conn.execute(
            "SELECT token_path FROM gmail_mailboxes WHERE email=?",
            (email,),
        ).fetchone()
    if not row:
        return None
    path = Path(row["token_path"])
    if not path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds, email)
    return creds


def mailbox_service(email: str):
    creds = load_credentials(email)
    if not creds or not creds.valid:
        raise RuntimeError(f"Gmail OAuth authorization missing/expired for {email}")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def mailbox_profile(email: str) -> dict:
    service = mailbox_service(email)
    return service.users().getProfile(userId="me").execute()


def list_recent_messages(email: str, query: str = "", max_results: int = 10) -> list[dict]:
    """Return message metadata only. No body/OTP extraction."""
    service = mailbox_service(email)
    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    return response.get("messages", [])


def get_message_headers(email: str, message_id: str) -> dict:
    """Return safe header metadata for auditing and sender matching."""
    service = mailbox_service(email)
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata",
             metadataHeaders=["From", "To", "Subject", "Date"])
        .execute()
    )
    headers = {}
    for header in msg.get("payload", {}).get("headers", []):
        name = header.get("name", "")
        value = header.get("value", "")
        if name in {"From", "To", "Subject", "Date"}:
            headers[name] = value
    return {"id": message_id, "headers": headers, "labelIds": msg.get("labelIds", [])}


@bp.route("/gmail/oauth/start")
def oauth_start():
    # This endpoint is intended for an ADMIN-only button/link.
    public_url = os.getenv("PUBLIC_URL", "").strip()
    owner = int(request.args.get("admin_id", "0"))
    if not public_url or owner <= 0:
        return "OAuth configuration is missing.", 400
    if owner != int(os.getenv("ADMIN_ID", "0")):
        return "Forbidden", 403
    url = create_authorization_url(public_url, owner)
    return redirect(url)


@bp.route(CALLBACK_PATH)
def oauth_callback():
    state = request.args.get("state", "")
    if not state:
        return "Missing OAuth state.", 400
    with _lock, closing(_connect_db()) as conn:
        info = conn.execute(
            """
            SELECT state, owner_user_id, created_at
            FROM gmail_oauth_states
            WHERE state=?
            """,
            (state,),
        ).fetchone()

        if info:
            conn.execute(
                "DELETE FROM gmail_oauth_states WHERE state=?",
                (state,),
            )
            conn.commit()

    if not info:
        return "Invalid or expired OAuth state.", 400

    public_url = os.getenv("PUBLIC_URL", "").strip()
    flow = _flow(public_url, state=state)
    flow.fetch_token(authorization_response=request.url)

    service = build("gmail", "v1", credentials=flow.credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "").strip().lower()
    if not email:
        return "Could not identify Gmail mailbox.", 400

    save_credentials(flow.credentials, email)
    return (
        "Gmail connected successfully. You may close this page and return to Telegram."
    )


def register_flask(app):
    init_db()
    app.register_blueprint(bp)
