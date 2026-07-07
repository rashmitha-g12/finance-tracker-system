"""
core/category_memory.py
------------------------
Learns from the categories you confirm or type in by hand, so the app gets
smarter the more you use it -- stored in the shared SQLite database
(core/db.py) rather than per-user JSON files, so everything lives in one
`.db` file.

Two things are remembered, each in its own table, keyed by username:

  1. Exact description -> category corrections. Tell it once that "PIZZA
     HUT" is "Foods" and it will suggest "Foods" again next time it sees
     that exact description.
  2. Any custom category names you've ever created (e.g. "Foods"), so they
     show up as real options in the category dropdown, the sidebar filter,
     and get a stable color in the charts.

Guest-mode corrections are never persisted, for the same reason manual
transactions aren't (see core/persistence.py): "guest" is one identity
shared by anyone who skips signup, so saving to disk would mix every
guest's corrections together. Guests still get live suggestions during
their session -- the memory just resets when the session ends.
"""

import streamlit as st

from core.db import get_connection
from core.ml_engine import CATEGORIES

GUEST_USERNAME = "guest"
_OVERRIDES_KEY = "category_overrides"
_CUSTOM_CATS_KEY = "custom_categories"


def _current_username() -> str:
    return st.session_state.get("username", GUEST_USERNAME)


def init_category_tables() -> None:
    """Create the category-memory tables if they don't already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS category_overrides (
                username TEXT NOT NULL,
                description_key TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (username, description_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_categories (
                username TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (username, category)
            )
            """
        )


def _normalize(description: str) -> str:
    return " ".join(str(description).strip().lower().split())


def _load_overrides_from_db(username: str) -> dict:
    init_category_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT description_key, category FROM category_overrides WHERE username = ?",
            (username,),
        ).fetchall()
    return {row["description_key"]: row["category"] for row in rows}


def _load_custom_categories_from_db(username: str) -> list:
    init_category_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT category FROM custom_categories WHERE username = ? ORDER BY category",
            (username,),
        ).fetchall()
    return [row["category"] for row in rows]


def init_category_memory() -> None:
    """Load the current user's learned overrides + custom categories into
    session_state. Safe to call multiple times (idempotent); only reads
    from the database the first time in a given session. Guests always
    start with an empty memory -- nothing is loaded or saved for them."""
    username = _current_username()
    if _OVERRIDES_KEY not in st.session_state:
        st.session_state[_OVERRIDES_KEY] = (
            {} if username == GUEST_USERNAME else _load_overrides_from_db(username)
        )
    if _CUSTOM_CATS_KEY not in st.session_state:
        st.session_state[_CUSTOM_CATS_KEY] = (
            [] if username == GUEST_USERNAME else _load_custom_categories_from_db(username)
        )


def reset_session_cache() -> None:
    """Drop the in-memory cache (not the database rows) so the next
    `init_category_memory()` call reloads fresh. Call this on logout --
    otherwise a second account logging in during the same browser session
    would keep seeing the previous account's categories."""
    st.session_state.pop(_OVERRIDES_KEY, None)
    st.session_state.pop(_CUSTOM_CATS_KEY, None)


def remember(description: str, category: str) -> None:
    """Record that `description` should map to `category` from now on, and
    register `category` as a known custom category if it isn't one of the
    five built-ins. Persisted immediately -- except for guests, whose
    corrections stay in-session only."""
    init_category_memory()
    key = _normalize(description)
    if not key or not category:
        return

    st.session_state[_OVERRIDES_KEY][key] = category
    is_new_custom = category not in CATEGORIES and category not in st.session_state[_CUSTOM_CATS_KEY]
    if is_new_custom:
        st.session_state[_CUSTOM_CATS_KEY].append(category)

    username = _current_username()
    if username == GUEST_USERNAME:
        return

    init_category_tables()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO category_overrides (username, description_key, category) VALUES (?, ?, ?) "
            "ON CONFLICT(username, description_key) DO UPDATE SET category = excluded.category",
            (username, key, category),
        )
        if is_new_custom:
            conn.execute(
                "INSERT OR IGNORE INTO custom_categories (username, category) VALUES (?, ?)",
                (username, category),
            )


def lookup(description: str):
    """Return a remembered category for this exact description, or None."""
    init_category_memory()
    return st.session_state[_OVERRIDES_KEY].get(_normalize(description))


def all_categories() -> list:
    """Built-in categories plus every custom category the user has ever added."""
    init_category_memory()
    customs = [c for c in st.session_state[_CUSTOM_CATS_KEY] if c not in CATEGORIES]
    return CATEGORIES + sorted(customs)


def get_overrides() -> dict:
    """The full {normalized description: category} memory, for bulk lookups
    (e.g. when categorizing an uploaded CSV)."""
    init_category_memory()
    return st.session_state[_OVERRIDES_KEY]
