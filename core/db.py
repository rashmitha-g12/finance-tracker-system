"""
core/db.py
----------
Shared SQLite connection for the whole app.

Everything the app persists -- user accounts, manually entered
transactions, and learned category corrections -- lives in this single
`.db` file (`data/users.db`) instead of being scattered across per-user
folders and mixed CSV/JSON formats. `core/auth.py`, `core/persistence.py`,
and `core/category_memory.py` each own their own tables in it, but all
connect through `get_connection()` here so there's exactly one file on disk.
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "users.db"


def get_connection() -> sqlite3.Connection:
    """Open a connection to the single shared database file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
