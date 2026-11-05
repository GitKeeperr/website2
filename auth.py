"""Google Identity Services authentication and server-controlled Konzei account roles.

No Google passwords, OAuth access tokens, ID tokens, or browser cookies are retained.
Persistent browser sessions are random tokens; only SHA-256 digests are stored.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
# Minimal local .env reader; never distribute this file with the application.
# Deliberately avoids shell expansion, commands, and accidental secrets in git.
def load_local_env(path: Path):
    if path.exists():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            if key.startswith('KONZEI_') or key == 'PORT':
                os.environ.setdefault(key, value.strip().strip('\"').strip("'"))

load_local_env(ROOT / '.env')
DATA = Path(os.getenv('KONZEI_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'accounts.sqlite3'
GOOGLE_CLIENT_ID = os.getenv('KONZEI_GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CONFIGURED = bool(GOOGLE_CLIENT_ID and not GOOGLE_CLIENT_ID.upper().startswith(('YOUR_', 'REPLACE_')))
OWNER_EMAIL = os.getenv('KONZEI_OWNER_EMAIL', '').strip().casefold()
PUBLIC_MODE = os.getenv('KONZEI_PUBLIC_MODE', '0').lower() in ('1', 'true', 'yes')
SECURE_COOKIES = PUBLIC_MODE or os.getenv('KONZEI_SECURE_COOKIES', '0').lower() in ('1', 'true', 'yes')
SESSION_SECONDS = 14 * 86400
COOKIE = 'konzei_session'
CSRF_COOKIE = 'konzei_csrf'
LOCK = threading.RLock()
router = APIRouter(prefix='/api/auth', tags=['Account'])
owner_router = APIRouter(prefix='/api/owner', tags=['Private owner controls'])


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout = 15000')
    db.execute('PRAGMA foreign_keys = ON')
    return db


def init_db():
    with LOCK, connect() as db:
        if os.name == 'posix':
            try:
                os.chmod(DATA, 0o700)
                os.chmod(DB_PATH, 0o600)
            except OSError:
                pass
        db.execute('PRAGMA journal_mode = WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          google_sub TEXT PRIMARY KEY,
          email TEXT NOT NULL,
          display_name TEXT NOT NULL,
          picture TEXT NOT NULL DEFAULT '',
          role TEXT NOT NULL CHECK (role IN ('owner','user')),
          disabled INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          last_login TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY,
          google_sub TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
          expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO settings(key, value) VALUES ('allow_signups', '1');
        INSERT OR IGNORE INTO settings(key, value) VALUES ('site_notice', '');
        CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
        ''')


init_db()


def config_value(key: str) -> str:
    with LOCK, connect() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else ''


def public_user(row: sqlite3.Row | dict) -> dict:
    return {k: row[k] for k in ('email', 'display_name', 'picture', 'role', 'created_at')}


def current_user(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE, '')
    if not raw or len(raw) > 200:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with LOCK, connect() as db:
        row = db.execute('''SELECT u.* FROM sessions s
             JOIN users u ON u.google_sub = s.google_sub
             WHERE s.token_hash=? AND s.expires_at > ? AND u.disabled = 0''',
             (digest, int(time.time()))).fetchone()
    if row is None:
        return None
    user = dict(row)
    # Roles are stored server-side. The configured owner email is never sent to other users.
    if user['role'] == 'owner' and (not OWNER_EMAIL or user['email'].casefold() != OWNER_EMAIL):
        user['role'] = 'user'
    return user


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, 'Sign in with Google to use Konzei Clips.')
    return user


def require_owner(request: Request) -> dict:
    user = require_user(request)
    if user['role'] != 'owner':
        raise HTTPException(403, 'Owner-only feature.')
    return user


def check_csrf(request: Request):
    cookie = request.cookies.get(CSRF_COOKIE, '')
    header = request.headers.get('x-konzei-csrf', '')
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(403, 'Security token expired. Refresh the page and try again.')


class LoginRequest(BaseModel):
    credential: str = Field(min_length=10, max_length=10000)


@router.get('/config')
def auth_config():
    csrf = secrets.token_urlsafe(32)
    resp = JSONResponse({'google_client_id': GOOGLE_CLIENT_ID, 'configured': GOOGLE_CONFIGURED,
                         'csrf_token': csrf, 'local_only': not PUBLIC_MODE})
    resp.set_cookie(CSRF_COOKIE, csrf, httponly=True, secure=SECURE_COOKIES,
                    samesite='strict', max_age=86400, path='/')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@router.get('/me')
def account_me(request: Request):
    user = current_user(request)
    return {'user': public_user(user) if user else None,
            'site_notice': config_value('site_notice') if user else ''}


def verify_google_id_token(token: str) -> dict:
    if not GOOGLE_CONFIGURED:
        raise HTTPException(503, 'Google sign-in is not configured yet. Set KONZEI_GOOGLE_CLIENT_ID in .env.')
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        identity = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)
    except Exception as exc:
        # Do not reveal external token details to the browser.
        raise HTTPException(401, 'Google could not verify this sign-in. Please try again.') from exc
    if not identity.get('sub') or identity.get('email_verified') is not True or not identity.get('email'):
        raise HTTPException(401, 'A verified Google email address is required.')
    return identity


@router.post('/google')
def login_with_google(payload: LoginRequest, request: Request):
    check_csrf(request)
    identity = verify_google_id_token(payload.credential)
    google_sub = str(identity['sub'])
    email = str(identity['email']).casefold()
    display_name = str(identity.get('name') or email.split('@')[0])[:150]
    picture = str(identity.get('picture') or '')[:600]
    # Gmail is authoritative for its address; do NOT trust email claims from the browser.
    eligible_owner = bool(OWNER_EMAIL and email == OWNER_EMAIL and email.endswith('@gmail.com'))
    with LOCK, connect() as db:
        # Bind the owner privilege to the first verified Google account for that email.
        bound = db.execute("SELECT value FROM settings WHERE key='owner_google_sub'").fetchone()
        if eligible_owner and not bound:
            db.execute("INSERT INTO settings(key, value) VALUES ('owner_google_sub', ?)", (google_sub,))
            bound_sub = google_sub
        else:
            bound_sub = bound['value'] if bound else None
        is_owner = eligible_owner and hmac.compare_digest(google_sub, bound_sub or '')
        existing = db.execute('SELECT disabled, created_at FROM users WHERE google_sub=?', (google_sub,)).fetchone()
        if existing and existing['disabled'] and not is_owner:
            raise HTTPException(403, 'This Konzei account is disabled.')
        signups = db.execute("SELECT value FROM settings WHERE key='allow_signups'").fetchone()
        if not existing and not is_owner and signups and signups['value'] == '0':
            raise HTTPException(403, 'New Konzei account registration is closed.')
        role = 'owner' if is_owner else 'user'
        db.execute('''INSERT INTO users(google_sub,email,display_name,picture,role,disabled,created_at,last_login)
          VALUES (?,?,?,?,?,0,?,?) ON CONFLICT(google_sub) DO UPDATE SET
          email=excluded.email, display_name=excluded.display_name, picture=excluded.picture,
          role=excluded.role, last_login=excluded.last_login''',
          (google_sub, email, display_name, picture, role, now(), now()))
        token = secrets.token_urlsafe(48)
        db.execute('INSERT INTO sessions(token_hash,google_sub,expires_at) VALUES (?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), google_sub, int(time.time()) + SESSION_SECONDS))
        db.execute('DELETE FROM sessions WHERE expires_at <= ?', (int(time.time()),))
        row = db.execute('SELECT * FROM users WHERE google_sub=?', (google_sub,)).fetchone()
    resp = JSONResponse({'user': public_user(row)})
    resp.set_cookie(COOKIE, token, httponly=True, secure=SECURE_COOKIES, samesite='lax',
                    max_age=SESSION_SECONDS, path='/')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@router.post('/logout')
def logout(request: Request):
    check_csrf(request)
    raw = request.cookies.get(COOKIE, '')
    if raw:
        with LOCK, connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',
                       (hashlib.sha256(raw.encode()).hexdigest(),))
    resp = JSONResponse({'signed_out': True})
    resp.delete_cookie(COOKIE, path='/')
    return resp


@owner_router.get('/overview')
def overview(request: Request):
    require_owner(request)
    with LOCK, connect() as db:
        users = db.execute('SELECT COUNT(*) n FROM users').fetchone()['n']
        disabled = db.execute('SELECT COUNT(*) n FROM users WHERE disabled=1').fetchone()['n']
        sessions = db.execute('SELECT COUNT(*) n FROM sessions WHERE expires_at>?', (int(time.time()),)).fetchone()['n']
        bound = db.execute("SELECT value FROM settings WHERE key='owner_google_sub'").fetchone()
    return {'users': users, 'disabled_users': disabled, 'active_sessions': sessions,
            'owner_bound': bool(bound), 'allow_signups': config_value('allow_signups') == '1',
            'site_notice': config_value('site_notice')}


@owner_router.get('/users')
def all_users(request: Request):
    require_owner(request)
    with LOCK, connect() as db:
        rows = db.execute('''SELECT google_sub,email,display_name,role,disabled,created_at,last_login
                             FROM users ORDER BY created_at DESC''').fetchall()
    return [dict(row) for row in rows]


class AccessUpdate(BaseModel):
    disabled: bool


@owner_router.patch('/users/{google_sub}/access')
def access_update(google_sub: str, payload: AccessUpdate, request: Request):
    owner = require_owner(request)
    if google_sub == owner['google_sub']:
        raise HTTPException(400, 'You cannot disable your own owner account.')
    with LOCK, connect() as db:
        row = db.execute('SELECT role FROM users WHERE google_sub=?', (google_sub,)).fetchone()
        if not row:
            raise HTTPException(404, 'Account not found.')
        if row['role'] == 'owner':
            raise HTTPException(403, 'Owner accounts cannot be disabled.')
        db.execute('UPDATE users SET disabled=? WHERE google_sub=?',
                   (int(payload.disabled), google_sub))
        if payload.disabled:
            db.execute('DELETE FROM sessions WHERE google_sub=?', (google_sub,))
    return {'updated': True, 'disabled': payload.disabled}


class SiteSettings(BaseModel):
    allow_signups: bool
    site_notice: str = Field('', max_length=300)


@owner_router.patch('/settings')
def update_settings(payload: SiteSettings, request: Request):
    require_owner(request)
    with LOCK, connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES ('allow_signups',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   ('1' if payload.allow_signups else '0',))
        db.execute("INSERT INTO settings(key,value) VALUES ('site_notice',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (payload.site_notice.strip(),))
    return {'allow_signups': payload.allow_signups, 'site_notice': payload.site_notice.strip()}
