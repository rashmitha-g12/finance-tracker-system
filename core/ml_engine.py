"""
core/ml_engine.py
------------------
Machine learning engine for the Personal Finance AI Tracker.

Trains a TF-IDF + Logistic Regression classifier on a curated set of bank
transaction description patterns and exposes a single categorization
function that returns a (category, confidence) pair. Falls back to
keyword-based rules whenever the model's confidence is too low to trust,
so every transaction always gets a sensible label.
"""

from typing import Tuple

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# --------------------------------------------------------------------------------------
# Category definitions
# --------------------------------------------------------------------------------------
CATEGORIES = ["Groceries", "Utilities", "Entertainment", "Salary", "Miscellaneous"]

CATEGORY_STYLE = {
    "Groceries": {"color": "#22c55e", "emoji": "🛒"},
    "Utilities": {"color": "#3b82f6", "emoji": "💡"},
    "Entertainment": {"color": "#a855f7", "emoji": "🎬"},
    "Salary": {"color": "#eab308", "emoji": "💵"},
    "Miscellaneous": {"color": "#64748b", "emoji": "🧾"},
}

CONFIDENCE_THRESHOLD = 0.35

_FALLBACK_PALETTE = [
    "#f97316", "#14b8a6", "#6366f1", "#ec4899",
    "#84cc16", "#0ea5e9", "#f43f5e", "#a3a3a3",
]


def style_for_category(category: str) -> dict:
    """Return a {'color', 'emoji'} style dict for any category, built-in or
    custom. Built-ins use their fixed style; custom categories get a stable
    color chosen deterministically from their name."""
    if category in CATEGORY_STYLE:
        return CATEGORY_STYLE[category]
    idx = sum(ord(ch) for ch in str(category)) % len(_FALLBACK_PALETTE)
    return {"color": _FALLBACK_PALETTE[idx], "emoji": "🏷️"}

# --------------------------------------------------------------------------------------
# Rule-based keyword fallback (used when ML confidence is low)
# --------------------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "Groceries": [
        "grocery", "supermarket", "walmart", "costco", "whole foods", "trader joe",
        "kroger", "safeway", "aldi", "publix", "food lion", "sprouts", "market",
        "rice", "milk", "bread", "eggs", "vegetable", "fruit", "chicken", "meat",
        "fish", "flour", "sugar", "cereal", "pasta", "cheese", "butter", "yogurt",
        "coffee beans", "tea leaves", "spices", "lentils", "beans", "onion",
        "potato", "tomato", "oil", "snacks", "produce", "bakery", "supermart",
    ],
    "Utilities": [
        "electric", "water bill", "water utility", "gas bill", "utility", "internet",
        "comcast", "xfinity", "at&t", "att wireless", "verizon", "spectrum",
        "power company", "broadband", "pg&e", "sewer", "electricity bill",
        "wifi bill", "mobile recharge", "phone bill", "gas cylinder", "lpg",
        "cable bill", "utility bill",
    ],
    "Entertainment": [
        "netflix", "spotify", "movie", "cinema", "amc", "regal", "hulu", "disney+",
        "concert", "steam", "playstation", "xbox", "game", "ticket", "live nation",
        "gaming", "music", "movie ticket", "theatre", "theater", "party", "club",
        "streaming",
    ],
    "Salary": [
        "payroll", "salary", "deposit from employer", "direct deposit", "paycheck",
        "wages", "employer", "bonus", "stipend", "income credit",
    ],
    "Miscellaneous": [],  # catch-all
}


def rule_based_category(description: str) -> str:
    """Simple keyword-matching fallback classifier."""
    desc = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc:
                return category
    return "Miscellaneous"


# --------------------------------------------------------------------------------------
# Synthetic labeled training data for the ML classifier
# (Broad enough to generalize to common real-world bank description patterns)
# --------------------------------------------------------------------------------------
TRAINING_DATA = [
    # Groceries
    ("WHOLE FOODS MARKET #123", "Groceries"),
    ("TRADER JOES GROCERY STORE", "Groceries"),
    ("COSTCO WHOLESALE CLUB", "Groceries"),
    ("SAFEWAY SUPERMARKET PURCHASE", "Groceries"),
    ("KROGER GROCERY STORE #45", "Groceries"),
    ("ALDI MARKET PURCHASE", "Groceries"),
    ("WALMART SUPERCENTER GROCERY", "Groceries"),
    ("PUBLIX SUPERMARKET", "Groceries"),
    ("FOOD LION GROCERY STORE", "Groceries"),
    ("SPROUTS FARMERS MARKET", "Groceries"),
    ("HARRIS TEETER GROCERY", "Groceries"),
    ("WEGMANS FOOD MARKET", "Groceries"),
    ("RICE", "Groceries"),
    ("MILK AND EGGS", "Groceries"),
    ("BREAD PURCHASE", "Groceries"),
    ("VEGETABLES", "Groceries"),
    ("FRESH FRUIT", "Groceries"),
    ("CHICKEN AND MEAT", "Groceries"),
    ("COOKING OIL", "Groceries"),
    ("FLOUR AND SUGAR", "Groceries"),
    ("SPICES AND LENTILS", "Groceries"),
    ("CEREAL AND PASTA", "Groceries"),
    ("CHEESE AND BUTTER", "Groceries"),
    ("LOCAL VEGETABLE MARKET", "Groceries"),
    ("SUPERMART GROCERY RUN", "Groceries"),
    # Utilities
    ("COMCAST CABLE BILL PAYMENT", "Utilities"),
    ("AT&T WIRELESS BILL", "Utilities"),
    ("ELECTRIC COMPANY PAYMENT", "Utilities"),
    ("WATER UTILITY BILL", "Utilities"),
    ("NATURAL GAS BILL PAYMENT", "Utilities"),
    ("VERIZON INTERNET BILL", "Utilities"),
    ("XFINITY INTERNET SERVICE", "Utilities"),
    ("CITY WATER AND SEWER PAYMENT", "Utilities"),
    ("PG&E ELECTRIC BILL", "Utilities"),
    ("SPECTRUM CABLE AND INTERNET", "Utilities"),
    ("T-MOBILE PHONE BILL", "Utilities"),
    ("CON EDISON ELECTRIC PAYMENT", "Utilities"),
    ("ELECTRICITY BILL PAYMENT", "Utilities"),
    ("WIFI BILL PAYMENT", "Utilities"),
    ("MOBILE RECHARGE", "Utilities"),
    ("GAS CYLINDER REFILL", "Utilities"),
    ("PHONE BILL PAYMENT", "Utilities"),
    # Entertainment
    ("NETFLIX.COM SUBSCRIPTION", "Entertainment"),
    ("SPOTIFY PREMIUM MONTHLY", "Entertainment"),
    ("AMC THEATERS TICKET PURCHASE", "Entertainment"),
    ("STEAM GAMES PURCHASE", "Entertainment"),
    ("XBOX LIVE SUBSCRIPTION", "Entertainment"),
    ("PLAYSTATION STORE PURCHASE", "Entertainment"),
    ("HULU SUBSCRIPTION PAYMENT", "Entertainment"),
    ("DISNEY+ MONTHLY SUBSCRIPTION", "Entertainment"),
    ("REGAL CINEMAS MOVIE TICKET", "Entertainment"),
    ("LIVE NATION CONCERT TICKET", "Entertainment"),
    ("APPLE TV+ SUBSCRIPTION", "Entertainment"),
    ("YOUTUBE PREMIUM SUBSCRIPTION", "Entertainment"),
    ("MOVIE TICKET", "Entertainment"),
    ("GAMING SUBSCRIPTION", "Entertainment"),
    ("MUSIC STREAMING SERVICE", "Entertainment"),
    ("PARTY EXPENSES", "Entertainment"),
    ("THEATRE SHOW TICKET", "Entertainment"),
    # Salary
    ("PAYROLL DEPOSIT ACME CORP", "Salary"),
    ("DIRECT DEPOSIT SALARY PAYMENT", "Salary"),
    ("EMPLOYER PAYCHECK DEPOSIT", "Salary"),
    ("BIWEEKLY SALARY PAYMENT", "Salary"),
    ("COMPANY PAYROLL DEPOSIT", "Salary"),
    ("WAGES DIRECT DEPOSIT", "Salary"),
    ("SALARY CREDIT XYZ INC", "Salary"),
    ("PAYCHECK DEPOSIT EMPLOYER", "Salary"),
    ("MONTHLY SALARY DEPOSIT", "Salary"),
    ("PAYROLL DIRECT DEPOSIT", "Salary"),
    ("EMPLOYER DIRECT DEPOSIT PAYROLL", "Salary"),
    ("ANNUAL BONUS PAYMENT", "Salary"),
    ("MONTHLY STIPEND CREDIT", "Salary"),
    # Miscellaneous
    ("UBER RIDE PAYMENT", "Miscellaneous"),
    ("AMAZON.COM PURCHASE", "Miscellaneous"),
    ("GYM MEMBERSHIP FITNESS CO", "Miscellaneous"),
    ("TARGET STORE PURCHASE", "Miscellaneous"),
    ("ATM CASH WITHDRAWAL", "Miscellaneous"),
    ("CVS PHARMACY PURCHASE", "Miscellaneous"),
    ("HOME DEPOT PURCHASE", "Miscellaneous"),
    ("INSURANCE PREMIUM PAYMENT", "Miscellaneous"),
    ("PARKING GARAGE FEE", "Miscellaneous"),
    ("BANK SERVICE FEE", "Miscellaneous"),
    ("LYFT RIDE PAYMENT", "Miscellaneous"),
    ("VENMO TRANSFER", "Miscellaneous"),
]


@st.cache_resource(show_spinner=False)
def train_model() -> Pipeline:
    """Train (and cache) a TF-IDF + Logistic Regression pipeline on the synthetic
    training set. Cached via st.cache_resource so it only trains once per session,
    regardless of how many times the app reruns."""
    train_df = pd.DataFrame(TRAINING_DATA, columns=["text", "label"])
    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )
    pipeline.fit(train_df["text"], train_df["label"])
    return pipeline


def get_model() -> Pipeline:
    """Convenience accessor so callers don't need to think about caching directly."""
    return train_model()


def classify_transaction(
    description: str,
    pipeline: Pipeline = None,
    threshold: float = CONFIDENCE_THRESHOLD,
    overrides: dict = None,
) -> Tuple[str, float]:
    """Classify a single transaction description.

    Returns a (category, confidence) tuple. Lookup order:
      1. `overrides` -- an exact-match dict of {normalized description: category}
         built from the user's own past corrections (see core/category_memory.py).
         A hit here always wins, with confidence 1.0, since it's user-confirmed.
      2. The ML model's top prediction, if its confidence is >= `threshold`.
      3. Keyword-based rules, as a last resort.
    """
    if overrides:
        key = " ".join(str(description).strip().lower().split())
        if key in overrides:
            return overrides[key], 1.0

    if pipeline is None:
        pipeline = get_model()
    proba = pipeline.predict_proba([description])[0]
    classes = pipeline.classes_
    best_idx = int(np.argmax(proba))
    best_label = classes[best_idx]
    best_conf = float(proba[best_idx])
    if best_conf < threshold:
        return rule_based_category(description), best_conf
    return best_label, best_conf


def categorize_dataframe(
    df: pd.DataFrame, pipeline: Pipeline = None, overrides: dict = None
) -> pd.DataFrame:
    """Add `Category` and `Confidence` columns to a transactions dataframe.

    Expects a `Description` column. Rows that already have a Category set
    (e.g. a transaction added by hand where the user picked/confirmed the
    category themselves) are left untouched -- only rows missing a Category
    get classified, using `overrides` first and the ML model/rules second.
    Returns a new dataframe (does not mutate the input).
    """
    if pipeline is None:
        pipeline = get_model()
    out = df.copy()

    if "Category" not in out.columns:
        out["Category"] = pd.NA
    if "Confidence" not in out.columns:
        out["Confidence"] = pd.NA

    needs_categorization = out["Category"].isna() | (out["Category"].astype(str).str.strip() == "")
    for idx in out.index[needs_categorization]:
        desc = str(out.at[idx, "Description"])
        cat, conf = classify_transaction(desc, pipeline, overrides=overrides)
        out.at[idx, "Category"] = cat
        out.at[idx, "Confidence"] = round(conf, 2)

    return out
