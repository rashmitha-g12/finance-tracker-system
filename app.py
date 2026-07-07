"""
app.py
------
Personal Finance AI Tracker -- main Streamlit entry point.

Wires together the ML engine (core/ml_engine.py), the data loader
(core/data_loader.py), and the manual transaction form
(core/transaction_form.py) into a single dashboard:

    - Side-by-side CSV upload + manual entry form
    - KPI metric cards (income, spend, net cash flow, savings rate)
    - Interactive Plotly charts (expenses by category, monthly trend)
    - A categorized transactions table + automated insights tab

Run with:  streamlit run app.py
"""

import streamlit as st

from core.auth_ui import render_auth_gate, render_logout_button

# --------------------------------------------------------------------------------------
# Page config
# --------------------------------------------------------------------------------------
st.set_page_config(page_title="Personal Finance AI Tracker", page_icon="💰", layout="wide")

st.markdown(
    """
    <style>
    .main > div { padding-top: 1.2rem; }
    .hero-banner {
        background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 50%, #ec4899 100%);
        padding: 1.6rem 2rem; border-radius: 18px; margin-bottom: 1.4rem;
        box-shadow: 0 8px 24px rgba(79,70,229,0.25);
    }
    .hero-banner h1 { color: white; margin: 0; font-size: 1.9rem; }
    .hero-banner p { color: rgba(255,255,255,0.9); margin: 0.3rem 0 0 0; font-size: 0.95rem; }
    div[data-testid="stMetric"] {
        background: white; border: 1px solid #eef0f4; border-radius: 14px;
        padding: 0.9rem 1rem; box-shadow: 0 2px 8px rgba(15,23,42,0.05);
    }
    div[data-testid="stForm"] {
        border: 1px solid #eef0f4; border-radius: 16px; padding: 1.4rem;
        background: #fafbff;
    }
    .intake-card {
        border: 1px solid #eef0f4; border-radius: 16px; padding: 1.2rem 1.4rem;
        background: white; height: 100%;
    }
    .stTabs [data-baseweb="tab"] { font-weight: 600; padding: 0.5rem 1.1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-banner">
        <h1>💰 Personal Finance AI Tracker</h1>
        <p>Upload a CSV or type transactions in by hand — either way, AI auto-categorizes
        your spending into Groceries, Utilities, Entertainment, Salary, and Miscellaneous.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------------------
# Authentication gate -- deliberately the ONLY thing imported/run before this
# point. core.auth_ui only pulls in sqlite3/hashlib/re (all standard library),
# so the login screen renders without waiting on pandas, scikit-learn, or
# plotly -- those are only imported below, once someone is actually logged
# in and the full dashboard is about to render.
# --------------------------------------------------------------------------------------
if not render_auth_gate():
    st.stop()
render_logout_button()

# --------------------------------------------------------------------------------------
# Heavy imports -- deferred until after login (see note above)
# --------------------------------------------------------------------------------------
import pandas as pd
import plotly.express as px

from core.data_loader import (
    calculate_metrics,
    category_totals,
    clean_transactions,
    flag_future_dates,
    generate_mock_data,
    load_csv,
    mock_data_csv_bytes,
    monthly_totals,
)
from core.ml_engine import categorize_dataframe, get_model, style_for_category
from core import category_memory
from core.transaction_form import get_manual_transactions, init_manual_transactions_state, render_transaction_form

# --------------------------------------------------------------------------------------
# State + model init
# --------------------------------------------------------------------------------------
init_manual_transactions_state()
pipeline = get_model()

# --------------------------------------------------------------------------------------
# Data intake: CSV upload + manual entry form, side by side
# --------------------------------------------------------------------------------------
upload_col, form_col = st.columns([2, 3], gap="large")

with upload_col:
    st.markdown('<div class="intake-card">', unsafe_allow_html=True)
    st.markdown("##### 📤 Upload Bank Transactions")
    uploaded_file = st.file_uploader(
        "CSV with columns: Date, Description, Amount", type=["csv"], label_visibility="visible"
    )
    st.download_button(
        "⬇️ Download sample CSV",
        data=mock_data_csv_bytes(),
        file_name="sample_transactions.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.caption("No CSV? Choose what to start with instead:")
    fallback_choice = st.radio(
        "If no CSV is uploaded, start with:",
        ["🧪 Sample data (20 demo transactions)", "🗒️ Nothing — I'll add transactions myself"],
        index=0,
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)

with form_col:
    st.markdown('<div class="intake-card">', unsafe_allow_html=True)
    render_transaction_form()
    st.markdown("</div>", unsafe_allow_html=True)

# --------------------------------------------------------------------------------------
# Build the working dataset: CSV takes priority; otherwise the chosen fallback
# --------------------------------------------------------------------------------------
if uploaded_file is not None:
    base_df, error = load_csv(uploaded_file)
    if error:
        st.error(error)
        st.stop()
elif fallback_choice.startswith("🧪"):
    base_df = generate_mock_data()
else:
    base_df = pd.DataFrame(columns=["Date", "Description", "Amount"])

manual_df = get_manual_transactions()
combined_raw = (
    pd.concat([base_df, manual_df], ignore_index=True) if not manual_df.empty else base_df.copy()
)

clean_df = clean_transactions(combined_raw)
if clean_df.empty:
    st.info(
        "No transactions yet. Upload a CSV, switch to sample data on the left, "
        "or add your first transaction by hand on the right. 👆"
    )
    st.stop()

overrides = category_memory.get_overrides()
df = categorize_dataframe(clean_df, pipeline, overrides=overrides)
df["Month"] = df["Date"].dt.to_period("M").astype(str)
df = flag_future_dates(df)

future_count = int(df["IsFuture"].sum())
if future_count > 0:
    with st.expander(
        f"⚠️ {future_count} transaction(s) are dated in the future -- real bank "
        "statements shouldn't have these. Click to review.",
        expanded=False,
    ):
        st.dataframe(
            df.loc[df["IsFuture"], ["Date", "Description", "Amount", "Category"]]
            .sort_values("Date"),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "This usually means a typo in a date field, a bad CSV export, or a "
            "scheduled/pending payment that hasn't actually happened yet. By "
            "default these are excluded from totals and charts below -- "
            "uncheck 'Exclude future-dated transactions' in the sidebar to include them."
        )

# --------------------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------------------
with st.sidebar:
    st.header("🔍 Filters")
    available_categories = sorted(set(category_memory.all_categories()) | set(df["Category"].unique()))
    cat_filter = st.multiselect("Categories", available_categories, default=available_categories)
    min_date, max_date = df["Date"].min().date(), df["Date"].max().date()
    date_range = st.date_input(
        "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    if future_count > 0:
        exclude_future = st.checkbox(
            "Exclude future-dated transactions",
            value=True,
            help="Keeps future-dated rows out of totals, charts, and insights.",
        )
    else:
        exclude_future = True
    st.markdown("---")
    st.caption(
        "Model: TF-IDF (1-2 grams) + Logistic Regression, with a keyword-rule "
        "fallback for low-confidence predictions -- plus a memory of your own corrections."
    )

filtered = df[df["Category"].isin(cat_filter)].copy()
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[
        (filtered["Date"] >= pd.to_datetime(start)) & (filtered["Date"] <= pd.to_datetime(end))
    ]
if exclude_future:
    filtered = filtered[~filtered["IsFuture"]]

if filtered.empty:
    st.info("No transactions match the current filters.")
    st.stop()

# --------------------------------------------------------------------------------------
# KPI metric cards
# --------------------------------------------------------------------------------------
metrics = calculate_metrics(filtered)

st.markdown("---")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("💵 Total Income", f"${metrics['total_income']:,.2f}")
k2.metric("💸 Total Spent", f"${metrics['total_spent']:,.2f}")
k3.metric("📈 Net Cash Flow", f"${metrics['net_cash_flow']:,.2f}")
k4.metric("🏦 Savings Rate", f"{metrics['savings_rate']:.1f}%")
k5.metric("🧾 Transactions", f"{metrics['transaction_count']}")

# --------------------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------------------
cat_totals_df = category_totals(filtered)
month_totals_df = monthly_totals(filtered)
color_map = {cat: style_for_category(cat)["color"] for cat in cat_totals_df["Category"].unique()}

chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    if not cat_totals_df.empty:
        fig_pie = px.pie(
            cat_totals_df, names="Category", values="Spend", hole=0.45,
            title="Expenses by Category", color="Category", color_discrete_map=color_map,
        )
        fig_pie.update_traces(textinfo="percent+label")
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No expense transactions to chart yet.")
with chart_col2:
    if not cat_totals_df.empty:
        fig_bar = px.bar(
            cat_totals_df, x="Category", y="Spend", color="Category",
            color_discrete_map=color_map, title="Total Spend by Category", text_auto=".2s",
        )
        fig_bar.update_layout(showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)

if not month_totals_df.empty:
    fig_line = px.line(
        month_totals_df, x="Month", y="Spend", markers=True, title="Monthly Spending Trend"
    )
    st.plotly_chart(fig_line, use_container_width=True)

# --------------------------------------------------------------------------------------
# Tabs: transactions table + automated insights
# --------------------------------------------------------------------------------------
tx_tab, insight_tab = st.tabs(["📁 Transactions", "💡 Insights"])

with tx_tab:
    st.subheader("Categorized Transactions")
    display_cols = ["Date", "Description", "Amount", "Category", "Confidence"]
    st.dataframe(
        filtered[display_cols].sort_values("Date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )
    out_csv = filtered[display_cols].to_csv(index=False)
    st.download_button(
        "⬇️ Download categorized CSV", data=out_csv,
        file_name="categorized_transactions.csv", mime="text/csv",
    )

with insight_tab:
    st.subheader("💡 Automated Insights")

    if metrics["top_category"]:
        st.info(
            f"Your highest spending category is **{metrics['top_category']}**, "
            f"totaling **${metrics['top_category_amount']:,.2f}**."
        )
    if metrics["highest_expense_month"]:
        st.info(
            f"Your highest expense month is **{metrics['highest_expense_month']}**, "
            f"with **${metrics['highest_expense_month_amount']:,.2f}** spent."
        )
    if not month_totals_df.empty:
        st.info(f"Average monthly spending across the period: **${month_totals_df['Spend'].mean():,.2f}**.")

    st.markdown("#### Category Breakdown")
    st.dataframe(
        cat_totals_df.rename(columns={"Spend": "Total Spent ($)"}),
        hide_index=True, use_container_width=True,
    )

    low_conf = filtered[filtered["Confidence"] < 0.5]
    if len(low_conf) > 0:
        st.warning(
            f"{len(low_conf)} transaction(s) had low-confidence categorization "
            "(model confidence < 0.5) and may be worth reviewing manually:"
        )
        st.dataframe(
            low_conf[["Date", "Description", "Amount", "Category", "Confidence"]],
            hide_index=True, use_container_width=True,
        )
    else:
        st.success("All transactions were categorized with high confidence. ✅")

st.markdown("---")
st.caption("Built with Streamlit, scikit-learn, and Plotly.")
