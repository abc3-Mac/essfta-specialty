"""Session auth: bcrypt passwords, signed session cookie, CSRF, login rate limit."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import bcrypt

SECRET = os.environ.get("SPECIALTY_SECRET_KEY", "")
if not SECRET:
    # dev fallback only; the Docker deploy always sets SPECIALTY_SECRET_KEY
    SECRET = "dev-" + hashlib.sha256(b"essfta-specialty-dev").hexdigest()

COOKIE = "essfta_specialty_session"
SESSION_TTL = 60 * 60 * 12  # 12 hours


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), pw_hash.encode())
    except ValueError:
        return False


def _sign(payload: bytes) -> str:
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def _unsign(token: str):
    try:
        p64, s64 = token.split(".")
        payload = base64.urlsafe_b64decode(p64)
        sig = base64.urlsafe_b64decode(s64)
        good = hmac.new(SECRET.encode(), payload, hashlib.sha256).digest()
        if hmac.compare_digest(sig, good):
            return json.loads(payload)
    except Exception:
        pass
    return None


def make_session(username: str) -> str:
    return _sign(json.dumps({
        "u": username,
        "t": int(time.time()),
        "csrf": secrets.token_hex(16),
    }).encode())


def read_session(token: str):
    data = _unsign(token or "")
    if not data or int(time.time()) - data.get("t", 0) > SESSION_TTL:
        return None
    return data


# ---- login rate limiting (in-memory; single-process app) ----
_attempts = {}  # ip -> [timestamps]
WINDOW, LIMIT = 600, 10


def rate_limited(ip: str) -> bool:
    cutoff = time.time() - WINDOW
    lst = [t for t in _attempts.get(ip, []) if t > cutoff]
    _attempts[ip] = lst
    return len(lst) >= LIMIT


def record_attempt(ip: str):
    _attempts.setdefault(ip, []).append(time.time())
