"""
core/session_manager.py
------------------------
Persistent login sessions, so refreshing the page doesn't log you out.

`st.session_state` is tied to the current browser *connection* -- Streamlit
opens a brand-new one (and therefore a brand-new, empty `session_state`)
every time the page reloads. Without something outside `session_state` to
recognize you, a refresh looks identical to a first-time visitor, which is
why it was sending you back to the login screen.

This stores a random, unguessable session token in the URL's query string
(`?session=...`) and in a database table. A valid, unexpired token is
treated as proof of a previous successful login, and is used to restore
`st.session_state["authenticated"]` / `["username"]` / `["full_name"]`
automatically on page load -- no password re-entry needed.

Guest sessions are intentionally NOT persisted this way, consistent with
the rest of the app's guest-mode policy (see core/persistence.py):
refreshing while in guest mode still returns you to the login screen,
by design, since guest data itself is never saved either.

Security note: because there's no cookie support without adding an extra
component library, the token lives in the URL rather than an HttpOnly
cookie. That means it can leak through browser history or a shared link
in a way a proper cookie wouldn't. Tokens are long (32 random bytes,
~43 characters) and expire after 30 days, but this is a reasonable
trade-off for a personal/demo project, not a bank-grade session mechanism.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import streamlit as st

from core.db import get_connection

SESSION_TTL_DAYS = 30
QUERY_PARAM_KEY = "session"


def init_sessions_table() -> None:
    """Create the sessions table if it doesn't already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )


def create_session(username: str, full_name: str) -> str:
    """Create a new persistent session row and return its token."""
    init_sessions_table()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, username, full_name, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, username, full_name, now.isoformat(), expires.isoformat()),
        )
    return token


def get_session(token: str) -> Optional[dict]:
    """Return {"username", "full_name"} for a valid, unexpired token, or
    None. An expired token is deleted the moment it's encountered."""
    if not token:
        return None
    init_sessions_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT username, full_name, expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return {"username": row["username"], "full_name": row["full_name"]}


def delete_session(token: str) -> None:
    if not token:
        return
    init_sessions_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def restore_session_from_query_params() -> bool:
    """If the URL has a valid session token, populate st.session_state and
    return True. Otherwise return False. Cheap to call on every rerun."""
    token = st.query_params.get(QUERY_PARAM_KEY)
    if not token:
        return False

    session = get_session(token)
    if session is None:
        # Stale or tampered-with token in the URL -- clear it rather than
        # leaving a dead token sitting in the address bar.
        st.query_params.pop(QUERY_PARAM_KEY, None)
        return False

    st.session_state["authenticated"] = True
    st.session_state["username"] = session["username"]
    st.session_state["full_name"] = session["full_name"]
    st.session_state["session_token"] = token
    return True


def start_persistent_session(username: str, full_name: str) -> None:
    """Call right after a successful login to create a token and place it
    in the URL, so the next page refresh can be recognized."""
    token = create_session(username, full_name)
    st.session_state["session_token"] = token
    st.query_params[QUERY_PARAM_KEY] = token


def end_persistent_session() -> None:
    """Call on logout to invalidate the token, both in the database and
    the URL, so it can't be reused."""
    token = st.session_state.get("session_token")
    if token:
        delete_session(token)
    st.query_params.pop(QUERY_PARAM_KEY, None)
    st.session_state.pop("session_token", None)