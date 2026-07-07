"""
core/persistence.py
--------------------
Manually entered transactions and global knowledge base manager.
Guarantees that guest transactions live exclusively in temporary session memory, 
while logged-in users are persisted securely in SQLite.
All users contribute safely to a shared global category autofill database.
"""

import pandas as pd
import streamlit as st
from core.db import get_connection

MANUAL_TX_COLUMNS = ["Date", "Description", "Amount", "Category", "Confidence"]
GUEST_USERNAME = "guest"
SESSION_TX_KEY = "manual_tx_df"


def _is_guest() -> bool:
    """Check if the current active session is an unauthenticated guest."""
    return st.session_state.get("username", GUEST_USERNAME) == GUEST_USERNAME


def init_manual_tx_table() -> None:
    """Create transaction tables and the global knowledge base table."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS global_category_suggestions (
                description TEXT PRIMARY KEY,
                suggested_category TEXT NOT NULL
            )
            """
        )


def get_global_suggestion(description: str) -> str:
    """Fetch a universally learned category suggestion for any description text (Case-insensitive)."""
    init_manual_tx_table()
    if not description:
        return ""
    
    clean_desc = str(description).strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT suggested_category FROM global_category_suggestions WHERE LOWER(description) = ?",
            (clean_desc,)
        ).fetchone()
    
    if row:
        if hasattr(row, "keys"):
            return str(row["suggested_category"])
        elif isinstance(row, (tuple, list)):
            return str(row[0])
        return str(row)
    return ""


def load_manual_transactions(username: str = None) -> pd.DataFrame:
    """Load transactions. Guests read from active session memory; users read from SQLite."""
    init_manual_tx_table()
    
    if _is_guest():
        if SESSION_TX_KEY not in st.session_state:
            st.session_state[SESSION_TX_KEY] = pd.DataFrame(columns=MANUAL_TX_COLUMNS)
        return st.session_state[SESSION_TX_KEY]

    # Registered User Mode: Fetch safely from the database file
    target_user = username or st.session_state.get("username")
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, description, amount, category, confidence "
            "FROM manual_transactions WHERE username = ? ORDER BY id",
            (target_user,),
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=MANUAL_TX_COLUMNS)

    data_list = []
    for row in rows:
        if hasattr(row, "keys"):
            data_list.append(dict(row))
        else:
            data_list.append({
                "date": row[0],
                "description": row[1],
                "amount": row[2],
                "category": row[3],
                "confidence": row[4]
            })

    df = pd.DataFrame(data_list).rename(
        columns={
            "date": "Date", "description": "Description", "amount": "Amount",
            "category": "Category", "confidence": "Confidence",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df[MANUAL_TX_COLUMNS]


def save_manual_transactions(df: pd.DataFrame, username: str = None) -> None:
    """Save transactions. Guests update memory only; users rewrite database tables."""
    init_manual_tx_table()
    
    # Step 1: Handle transaction row tracking isolation
    if _is_guest():
        st.session_state[SESSION_TX_KEY] = df.copy()
    else:
        target_user = username or st.session_state.get("username")
        with get_connection() as conn:
            conn.execute("DELETE FROM manual_transactions WHERE username = ?", (target_user,))
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT INTO manual_transactions "
                    "(username, date, description, amount, category, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        target_user,
                        pd.Timestamp(row["Date"]).strftime("%Y-%m-%d"),
                        str(row["Description"]).strip(),
                        float(row["Amount"]),
                        str(row["Category"]).strip(),
                        float(row["Confidence"]),
                    ),
                )

    with get_connection() as conn:
        for _, row in df.iterrows():
            desc_clean = str(row["Description"]).strip()
            cat_clean = str(row["Category"]).strip()
            
            if desc_clean and cat_clean:
                conn.execute(
                    """
                    INSERT INTO global_category_suggestions (description, suggested_category)
                    VALUES (?, ?)
                    ON CONFLICT(description) DO UPDATE SET suggested_category = excluded.suggested_category
                    """,
                    (desc_clean, cat_clean)
                )


def clear_manual_transactions_file(username: str = None) -> None:
    """Wipe transaction records cleanly without purging learned global logic entries."""
    init_manual_tx_table()
    if _is_guest():
        st.session_state[SESSION_TX_KEY] = pd.DataFrame(columns=MANUAL_TX_COLUMNS)
    else:
        target_user = username or st.session_state.get("username")
        with get_connection() as conn:
            conn.execute("DELETE FROM manual_transactions WHERE username = ?", (target_user,))
