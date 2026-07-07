"""
core/auth.py
------------
SQLite-backed user accounts: signup, login, password hashing, and
password recovery via a security question (since this app has no email
integration to send reset links to).

Each user gets an isolated slice of the app's data (see core/persistence.py
and core/category_memory.py, which key their storage off the logged-in
username) so multiple people can use the same deployed app without ever
seeing each other's transactions.

Passwords -- and security-question answers -- are never stored in plain
text. Each is hashed with PBKDF2-HMAC-SHA256 and a unique random salt,
using only Python's standard library (hashlib + secrets), so this adds
zero new dependencies. For a real production deployment, consider a
battle-tested library like `bcrypt` or `argon2-cffi` instead -- they're
more resistant to GPU-based cracking and are the current industry standard.
"""

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Tuple

from core.db import get_connection

PBKDF2_ITERATIONS = 200_000
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
FULL_NAME_PATTERN = re.compile(r"^[A-Z][a-z]{2,24}(\s[A-Z][a-z]{1,24})?$")

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What was the name of the town where you were born?",
    "What was your childhood nickname?",
    "What was the make of your first car?",
    "What is your favorite book?",
]


def init_db() -> None:
    """Create the users table if needed, and migrate older databases that
    predate security questions. Safe to call every run."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                security_question TEXT,
                security_answer_hash TEXT,
                security_answer_salt TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        migrations = [
            ("security_question", "ALTER TABLE users ADD COLUMN security_question TEXT"),
            ("security_answer_hash", "ALTER TABLE users ADD COLUMN security_answer_hash TEXT"),
            ("security_answer_salt", "ALTER TABLE users ADD COLUMN security_answer_salt TEXT"),
        ]
        for col, ddl in migrations:
            if col not in existing_cols:
                conn.execute(ddl)


def _hash_secret(secret: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """Return (hash_hex, salt_hex), generating a new random salt if none is given.
    Used for both passwords and security-question answers."""
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def is_valid_username(username: str) -> bool:
    """3-20 characters: letters, numbers, and underscores only."""
    return bool(USERNAME_PATTERN.match(username or ""))

def is_valid_full_name(fullname:str)->bool:
    """3-50 characters: only letters and spaces allowed.. with first letter Capital"""
    return bool(FULL_NAME_PATTERN.match(fullname or ""))

def username_exists(username: str) -> bool:
    
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        return row is not None


def create_user(
    username: str, full_name: str, password: str, security_question: str, security_answer: str
) -> Tuple[bool, str]:
    """Create a new user account. Returns (success, message)."""
    init_db()
    username = (username or "").strip()
    full_name = (full_name or "").strip()
    security_answer = (security_answer or "").strip()

    if not is_valid_username(username):
        return False, "Username must be 3-20 characters: letters, numbers, and underscores only."
    if not is_valid_full_name(full_name):
        return False, "FullName must be 3-50 characters with first letter capital."
    if not security_question:
        return False, "Please choose a security question."
    if not security_answer:
        return False, "Please answer the security question -- it's how you'll reset your password later."
    if username_exists(username):
        return False, "That username is already taken."

    password_hash, salt = _hash_secret(password)
    # Answers are normalized to lowercase before hashing so "Rex" and "rex"
    # both work later -- security answers shouldn't be case-sensitive.
    answer_hash, answer_salt = _hash_secret(security_answer.lower())
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, full_name, password_hash, salt, "
                "security_question, security_answer_hash, security_answer_salt, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    username, full_name, password_hash, salt,
                    security_question, answer_hash, answer_salt,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "That username is already taken."


def verify_login(username: str, password: str) -> Tuple[bool, str, Optional[str]]:
    """Check a username/password pair. Returns (success, message, full_name_or_None)."""
    init_db()
    username = (username or "").strip()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT full_name, password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None:
        return False, "No account found with that username.", None

    expected_hash, _ = _hash_secret(password, bytes.fromhex(row["salt"]))
    if secrets.compare_digest(expected_hash, row["password_hash"]):
        return True, "Login successful.", row["full_name"]
    return False, "Incorrect password.", None


def get_security_question(username: str) -> Optional[str]:
    """Return the account's security question, or None if the username
    doesn't exist (or predates security questions being added)."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT security_question FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
    return row["security_question"] if row and row["security_question"] else None


def verify_security_answer(username: str, answer: str) -> bool:
    """Check a security-question answer against the stored hash."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT security_answer_hash, security_answer_salt FROM users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()
    if row is None or not row["security_answer_hash"]:
        return False
    expected_hash, _ = _hash_secret((answer or "").strip().lower(), bytes.fromhex(row["security_answer_salt"]))
    return secrets.compare_digest(expected_hash, row["security_answer_hash"])


def reset_password(username: str, new_password: str) -> Tuple[bool, str]:
    """Set a new password for an account, after the caller has already
    verified the security answer. Returns (success, message)."""
    init_db()
    username = (username or "").strip()
    if not username_exists(username):
        return False, "No account found with that username."
    password_hash, salt = _hash_secret(new_password)
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
            (password_hash, salt, username),
        )
    return True, "Password reset successfully."
