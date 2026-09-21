from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

PBKDF_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ROUNDS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ROUNDS)
    return hmac.compare_digest(got, expected)


def _ser() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret, salt="siemed-auth")


def make_token(payload: dict) -> str:
    return _ser().dumps(payload)


def read_token(token: str, max_age: int = 60 * 60 * 14) -> dict | None:
    try:
        return _ser().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def booking_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
