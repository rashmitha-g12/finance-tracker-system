"""
core/transaction_form.py
-------------------------
A self-contained Streamlit form component for manually adding a single
transaction, plus the session-state helpers that back it.

Behavior:
  - As you type a description, the app first checks if it has *seen and
    learned* this exact description before (core/category_memory.py); if
    so, it suggests that remembered category. Otherwise it asks the ML
    model (core/ml_engine.py) for its best guess.
  - You always get the final say: a dropdown lets you accept the
    suggestion, pick a different built-in category, or type a brand new
    custom category.
  - Whatever you confirm is remembered (core/category_memory.py) so the
    same description -- or that custom category -- is recognized
    immediately next time, anywhere in the app.
  - Every manually added transaction is mirrored to disk
    (core/persistence.py) so it survives a browser refresh or the app
    restarting, not just the current session.

Because `core/ml_engine.categorize_dataframe` only predicts categories for
rows that don't already have one, a manually chosen category is never
silently overwritten by the model later.
"""

from datetime import datetime
from core.persistence import get_global_suggestion
import pandas as pd
import streamlit as st

from core import category_memory, persistence
from core.ml_engine import CATEGORIES, classify_transaction, get_model, style_for_category

MANUAL_TX_KEY = "manual_transactions"
CUSTOM_CATEGORY_OPTION = "✏️ Custom category..."

# Widget/session-state keys reset together after a successful submit.
_FIELD_KEYS = ["txn_desc", "txn_amount", "txn_category", "txn_custom_category", "_txn_last_desc"]


def init_manual_transactions_state() -> None:
    """Ensure the session-state store for manual transactions exists,
    loading any previously saved ones from disk on first use in a session.

    Safe to call multiple times (idempotent) -- should be called once near
    the top of app.py before any other module touches manual transactions.
    """
    if MANUAL_TX_KEY not in st.session_state:
        st.session_state[MANUAL_TX_KEY] = persistence.load_manual_transactions()
    category_memory.init_category_memory()


def get_manual_transactions() -> pd.DataFrame:
    """Return the current session's manually entered transactions."""
    init_manual_transactions_state()
    return st.session_state[MANUAL_TX_KEY]


def reset_session_cache() -> None:
    """Drop the in-memory cache (not the on-disk file) so the next
    `init_manual_transactions_state()` call reloads fresh from disk. Call
    this on logout -- otherwise a second account logging in during the
    same browser session would keep seeing the previous account's
    transactions and in-progress form drafts."""
    st.session_state.pop(MANUAL_TX_KEY, None)
    for key in _FIELD_KEYS:
        st.session_state.pop(key, None)


def clear_manual_transactions() -> None:
    """Wipe all manually entered transactions, in this session and on disk.

    Note: this does NOT forget learned category corrections or custom
    categories (core/category_memory.py) -- that knowledge is kept
    separately since it's generally still useful going forward.
    """
    st.session_state[MANUAL_TX_KEY] = pd.DataFrame(columns=persistence.MANUAL_TX_COLUMNS)
    persistence.clear_manual_transactions_file()


def _category_chip(category: str, label: str = "") -> str:
    style = style_for_category(category)
    prefix = f"{label} " if label else ""
    return (
        f'{prefix}<span style="display:inline-block;padding:0.2rem 0.7rem;'
        f'border-radius:999px;font-size:0.8rem;font-weight:600;color:white;'
        f'background:{style["color"]}">{style["emoji"]} {category}</span>'
    )


def _suggest_category(description: str, pipeline) -> tuple:
    """Return (category, confidence, source) for a description, checking
    remembered corrections before falling back to the ML model."""
    remembered = category_memory.lookup(description)
    if remembered:
        return remembered, 1.0, "remembered"
    cat, conf = classify_transaction(description, pipeline, overrides=category_memory.get_overrides())
    return cat, conf, "ai"

@st.dialog("Confirm Action")
def confirm_clear_all():
    st.write("Are you sure want to clear ALL transactions?")
    col1,col2=st.columns(2)
    with col1:
        if st.button("Yes, Clear All",type="primary",use_container_width=True):
            clear_manual_transactions()
            st.rerun()
    with col2:
        if st.button("Cancel",type="secondary",use_container_width=True):
            st.rerun()

@st.dialog("Confirm Action")
def confirm_clear(row,idx):
    st.write(f"Are you sure want to delete the transaction : **{row['Date']} - {row['Description']} ({row['Category']})** ?")
    col1,col2=st.columns(2)
    with col1:
        if st.button("Yes, Clear",type="primary",use_container_width=True):
            st.session_state[MANUAL_TX_KEY] = (
                    st.session_state[MANUAL_TX_KEY].drop(index=idx).reset_index(drop=True)
            )
            persistence.save_manual_transactions(st.session_state[MANUAL_TX_KEY])
            st.rerun()
    with col2:
        if st.button("Cancel",type="secondary",use_container_width=True):
            st.rerun()
   
def render_transaction_form() -> None:
    """Render the manual transaction entry form.

    Plain widgets (not `st.form`) are used deliberately: the description
    field needs to trigger a rerun on every keystroke so the category
    suggestion -- and the dropdown default -- can update live. Call this
    from within a `with column:` block in app.py to place it side-by-side
    with other dashboard elements.
    """
    init_manual_transactions_state()
    pipeline = get_model()

    st.markdown("##### ✍️ Add a Transaction")
    st.caption("The app suggests a category as you type — you always get the final say.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.date_input(
            "📅 Date", value=datetime.today(), max_value=datetime.today(), key="txn_date",
            help="Bank transactions are settled, historical records -- future dates aren't allowed.",
        )
        st.radio("Type", ["Expense", "Income"], horizontal=True, key="txn_type")
    with col_b:
        st.text_input("📝 Description", placeholder="e.g. Whole Foods Market", key="txn_desc")
        st.number_input("💲 Amount", min_value=0.0, step=1.00, format="%.2f", key="txn_amount")

    description = st.session_state.get("txn_desc", "").strip()
    source=None
    pred_cat=None
    pred_conf=1.0
    if description:
        global_saved_cat=get_global_suggestion(description)
        if global_saved_cat:
            pred_cat=global_saved_cat
            source="remembered"
        else:
            pred_cat, pred_conf, source = _suggest_category(description, pipeline)
    else:
        pred_cat, pred_conf, source = None, 0.0, None

    if description != st.session_state.get("_txn_last_desc"):
        st.session_state["txn_category"] = pred_cat if pred_cat else CATEGORIES[-1]
        st.session_state["_txn_last_desc"] = description

    if description:
        if source == "remembered":
            st.markdown(
                f'📚 Remembered from past transactions: {_category_chip(pred_cat)} &nbsp; confidence: **{pred_conf:.0%}**',
                unsafe_allow_html=True,
            )
        else:
            if pred_cat:
                st.markdown(
                    f'🤖 AI suggests: {_category_chip(pred_cat)} &nbsp; confidence: **{pred_conf:.0%}**',
                    unsafe_allow_html=True,
            )

    st.caption("Not right? Choose a different category, or type your own:")
    
    base_options = category_memory.all_categories()
    if pred_cat and (pred_cat not in base_options):
        dropdown_options = [pred_cat] + base_options + [CUSTOM_CATEGORY_OPTION]
    else:
        dropdown_options = base_options + [CUSTOM_CATEGORY_OPTION]
        
    category_choice = st.selectbox("Category", options=dropdown_options, key="txn_category")

    final_category = category_choice
    if category_choice == CUSTOM_CATEGORY_OPTION:
        st.text_input(
            "Custom category name", key="txn_custom_category", placeholder="e.g. Foods, Travel"
        )
        typed = (st.session_state.get("txn_custom_category") or "").strip()
        final_category = typed if typed else "Miscellaneous"
        if typed:
            st.markdown(_category_chip(final_category, "Will be saved as:"), unsafe_allow_html=True)

    add_clicked = st.button("➕ Add Transaction", use_container_width=True)

    if add_clicked:
        amount = st.session_state.get("txn_amount", 0.0)
        entry_date = st.session_state.get("txn_date")
        if not description:
            st.error("Please enter a description.")
        elif amount <= 0:
            st.error("Please enter an amount greater than 0.")
        elif entry_date and entry_date > datetime.today().date():
            st.error("The date can't be in the future -- bank transactions are historical records.")
        else:
            signed_amount = amount if st.session_state["txn_type"] == "Income" else -amount
            was_overridden = pred_cat is not None and final_category != pred_cat

            new_row = pd.DataFrame(
                [{
                    "Date": pd.to_datetime(st.session_state["txn_date"]),
                    "Description": description,
                    "Amount": signed_amount,
                    "Category": final_category,
                    "Confidence": 1.0,  # human-confirmed
                }]
            )
            st.session_state[MANUAL_TX_KEY] = pd.concat(
                [st.session_state[MANUAL_TX_KEY], new_row], ignore_index=True
            )
            persistence.save_manual_transactions(st.session_state[MANUAL_TX_KEY])
            category_memory.remember(description, final_category)

            note = "your override" if was_overridden else "AI suggestion"
            st.success(f"Added! Saved as {_category_chip(final_category)} ({note}).")

            for key in _FIELD_KEYS:
                st.session_state.pop(key, None)
            st.rerun()

    manual_df = st.session_state[MANUAL_TX_KEY]
    if not manual_df.empty:
        st.markdown("###### Added this session")
        preview = manual_df.copy()
        preview["Date"] = pd.to_datetime(preview["Date"]).dt.date

        header_cols = st.columns([1.1, 2.4, 1.1, 1.5, 0.9, 0.6])
        for col, label in zip(header_cols, ["Date", "Description", "Amount", "Category", "Conf.", ""]):
            if label:
                col.markdown(f"**{label}**")

        for idx, row in preview.iterrows():
            c1, c2, c3, c4, c5, c6 = st.columns([1.3, 2.0, 1.1, 1.7, 0.9, 0.8])
            c1.write(str(row["Date"]))
            c2.write(row["Description"])
            c3.write(f"${row['Amount']:,.2f}")
            c4.markdown(_category_chip(row["Category"]), unsafe_allow_html=True)
            c5.write(f"{row['Confidence']:.0%}")
            if c6.button("🗑️", key=f"del_manual_{idx}", help="Delete this transaction"):
                confirm_clear(row,idx)

        st.markdown("")
        if st.button("🗑️ Clear all manually added transactions"):
            confirm_clear_all()
