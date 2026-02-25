from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app import db

PBKDF2_ALGO = "sha256"
PBKDF2_ITERATIONS = 260_000
SESSION_DURATION_HOURS = 12


class AuthError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    password = password.strip()
    if len(password) < 8:
        raise AuthError("Passord ma vaere minst 8 tegn")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(PBKDF2_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_{PBKDF2_ALGO}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        method, iterations_str, salt_hex, digest_hex = encoded_hash.split("$", maxsplit=3)
    except ValueError:
        return False
    if not method.startswith("pbkdf2_"):
        return False
    algo = method.split("_", maxsplit=1)[1]
    try:
        iterations = int(iterations_str)
    except ValueError:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected_digest)


def has_any_users() -> bool:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS count_value FROM users").fetchone()
        assert row is not None
        return int(row["count_value"]) > 0
    finally:
        conn.close()


def create_user(*, username: str, password: str, is_admin: bool = True) -> int:
    username = username.strip()
    if len(username) < 3:
        raise AuthError("Brukernavn ma vaere minst 3 tegn")
    password_hash = hash_password(password)
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, active)
            VALUES (?, ?, ?, 1)
            """,
            (username, password_hash, 1 if is_admin else 0),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise AuthError("Brukernavn finnes allerede") from exc
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(username.strip())
    if user is None or not user["active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def create_session(*, user_id: int, duration_hours: int = SESSION_DURATION_HOURS) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = (_utcnow() + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO user_sessions (token, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (token, user_id, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def clear_session(token: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def cleanup_expired_sessions() -> None:
    now = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
        conn.commit()
    finally:
        conn.close()


def get_user_by_session_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    cleanup_expired_sessions()
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT u.*
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
              AND u.active = 1
            """,
            (token,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

