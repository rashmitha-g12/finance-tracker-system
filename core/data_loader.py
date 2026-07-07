"""
core/data_loader.py
--------------------
Data ingestion and metrics utilities for the Personal Finance AI Tracker.

Responsible for:
    - Loading and validating user-uploaded CSVs
    - Generating a 20-row mock dataset for instant demoing
    - Cleaning/coercing raw transaction data
    - Computing headline KPI metrics (income, spend, net cash flow, savings rate)
    - Aggregating spend by category and by month for charting

This module is UI-agnostic (no Streamlit widgets) except for the CSV read,
so its functions are easy to unit test in isolation.
"""

import io
from datetime import date
from typing import Optional, Tuple

import pandas as pd

REQUIRED_COLUMNS = {"Date", "Description", "Amount"}


# --------------------------------------------------------------------------------------
# Mock dataset
# --------------------------------------------------------------------------------------
def generate_mock_data() -> pd.DataFrame:
    """Return a 20-row synthetic transaction dataset for instant testing/demoing."""
    rows = [
        ("2024-01-03", "WHOLE FOODS MARKET #123", -85.32),
        ("2024-01-05", "NETFLIX.COM SUBSCRIPTION", -15.99),
        ("2024-01-07", "COMCAST CABLE BILL PAYMENT", -75.00),
        ("2024-01-15", "PAYROLL DEPOSIT ACME CORP", 3200.00),
        ("2024-01-18", "STEAM GAMES PURCHASE", -29.99),
        ("2024-01-20", "TRADER JOES GROCERY STORE", -62.15),
        ("2024-01-22", "AT&T WIRELESS BILL", -60.00),
        ("2024-01-25", "AMC THEATERS TICKET PURCHASE", -24.50),
        ("2024-01-28", "UBER RIDE PAYMENT", -18.75),
        ("2024-02-01", "COSTCO WHOLESALE CLUB", -145.60),
        ("2024-02-03", "SPOTIFY PREMIUM MONTHLY", -9.99),
        ("2024-02-05", "ELECTRIC COMPANY PAYMENT", -95.40),
        ("2024-02-15", "PAYROLL DEPOSIT ACME CORP", 3200.00),
        ("2024-02-17", "AMAZON.COM PURCHASE", -55.20),
        ("2024-02-19", "SAFEWAY SUPERMARKET PURCHASE", -70.10),
        ("2024-02-22", "WATER UTILITY BILL", -40.00),
        ("2024-02-25", "XBOX LIVE SUBSCRIPTION", -12.99),
        ("2024-03-02", "KROGER GROCERY STORE #45", -90.45),
        ("2024-03-05", "GYM MEMBERSHIP FITNESS CO", -49.99),
        ("2024-03-15", "PAYROLL DEPOSIT ACME CORP", 3200.00),
    ]
    return pd.DataFrame(rows, columns=["Date", "Description", "Amount"])


def mock_data_csv_bytes() -> str:
    """Return the mock dataset serialized as a CSV string (for a download button)."""
    buffer = io.StringIO()
    generate_mock_data().to_csv(buffer, index=False)
    return buffer.getvalue()


# --------------------------------------------------------------------------------------
# CSV loading + cleaning
# --------------------------------------------------------------------------------------
def load_csv(uploaded_file) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Read and validate an uploaded CSV file-like object.

    Returns a (dataframe, error_message) tuple. Exactly one of the two will
    be None: a successful read returns (df, None); a failure returns
    (None, "human readable error").
    """
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as exc:  # noqa: BLE001 - surface any parse error to the user
        return None, f"Could not read CSV: {exc}"

    if not REQUIRED_COLUMNS.issubset(set(df.columns)):
        missing = sorted(REQUIRED_COLUMNS)
        return None, f"CSV must contain the columns: {missing}. Found: {list(df.columns)}"

    return df, None


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce types and drop rows that can't be used (bad dates/amounts)."""
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce")
    out["Description"] = out["Description"].astype(str)
    out = out.dropna(subset=["Date", "Amount", "Description"]).reset_index(drop=True)
    return out


def flag_future_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Add an `IsFuture` boolean column marking rows dated after today.

    Real bank statements only ever contain settled, historical transactions
    -- a future date usually means a data-entry mistake, a bad export, or a
    scheduled/pending transaction that hasn't actually happened yet. Rather
    than silently dropping such rows (the CSV might be legitimate and the
    user should decide), this just flags them so the caller can warn about
    and optionally exclude them.
    """
    out = df.copy()
    today = pd.Timestamp(date.today())
    out["IsFuture"] = out["Date"] > today
    return out


# --------------------------------------------------------------------------------------
# KPI metrics
# --------------------------------------------------------------------------------------
def calculate_metrics(df: pd.DataFrame) -> dict:
    """Compute headline KPIs for a categorized transactions dataframe.

    Expects columns: Date, Description, Amount, and (optionally) Category.
    Returns a dict with: total_income, total_spent, net_cash_flow,
    savings_rate, transaction_count, top_category, top_category_amount,
    highest_expense_month, highest_expense_month_amount.
    """
    empty_result = {
        "total_income": 0.0,
        "total_spent": 0.0,
        "net_cash_flow": 0.0,
        "savings_rate": 0.0,
        "transaction_count": 0,
        "top_category": None,
        "top_category_amount": 0.0,
        "highest_expense_month": None,
        "highest_expense_month_amount": 0.0,
    }
    if df.empty:
        return empty_result

    total_income = float(df.loc[df["Amount"] > 0, "Amount"].sum())
    total_spent = float(df.loc[df["Amount"] < 0, "Amount"].sum().__abs__())
    net_cash_flow = total_income - total_spent
    savings_rate = (net_cash_flow / total_income * 100.0) if total_income > 0 else 0.0

    cat_df = category_totals(df)
    top_category, top_category_amount = None, 0.0
    if not cat_df.empty:
        top_row = cat_df.iloc[0]
        top_category, top_category_amount = top_row["Category"], float(top_row["Spend"])

    month_df = monthly_totals(df)
    highest_expense_month, highest_expense_month_amount = None, 0.0
    if not month_df.empty:
        top_month_row = month_df.loc[month_df["Spend"].idxmax()]
        highest_expense_month = top_month_row["Month"]
        highest_expense_month_amount = float(top_month_row["Spend"])

    return {
        "total_income": total_income,
        "total_spent": total_spent,
        "net_cash_flow": net_cash_flow,
        "savings_rate": savings_rate,
        "transaction_count": int(len(df)),
        "top_category": top_category,
        "top_category_amount": top_category_amount,
        "highest_expense_month": highest_expense_month,
        "highest_expense_month_amount": highest_expense_month_amount,
    }


def category_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Total spend per category, excluding Salary (treated as income, not spend).

    Returns columns: Category, Spend -- sorted descending by Spend.
    """
    if df.empty or "Category" not in df.columns:
        return pd.DataFrame(columns=["Category", "Spend"])
    spend_df = df[(df["Amount"] < 0) & (df["Category"] != "Salary")].copy()
    if spend_df.empty:
        return pd.DataFrame(columns=["Category", "Spend"])
    spend_df["Spend"] = spend_df["Amount"].abs()
    return (
        spend_df.groupby("Category")["Spend"]
        .sum()
        .reset_index()
        .sort_values("Spend", ascending=False)
        .reset_index(drop=True)
    )


def monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Total spend per calendar month, excluding Salary (income).

    Returns columns: Month, Spend -- sorted chronologically.
    """
    if df.empty or "Category" not in df.columns:
        return pd.DataFrame(columns=["Month", "Spend"])
    spend_df = df[(df["Amount"] < 0) & (df["Category"] != "Salary")].copy()
    if spend_df.empty:
        return pd.DataFrame(columns=["Month", "Spend"])
    spend_df["Spend"] = spend_df["Amount"].abs()
    spend_df["Month"] = spend_df["Date"].dt.to_period("M").astype(str)
    return (
        spend_df.groupby("Month")["Spend"]
        .sum()
        .reset_index()
        .sort_values("Month")
        .reset_index(drop=True)
    )
