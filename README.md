# 💰 Personal Finance AI Tracker
A student portfolio project built to explore data engineering and automated categorization.
A Streamlit dashboard that auto-categorizes bank transactions using a
TF-IDF + Logistic Regression classifier (with a keyword-rule fallback),
remembers your own corrections over time, and surfaces spending KPIs
through interactive Plotly charts.

## Project Structure

```
finance_tracker/
├── app.py                     # Main entry point / dashboard layout
├── requirements.txt
├── data/                       # Created automatically
│   └── users.db                 # Database: accounts, transactions, category memory
└── core/
    ├── __init__.py
    ├── db.py                     # Shared SQLite connection used by every table below
    ├── ml_engine.py              # TF-IDF + Logistic Regression categorizer
    ├── data_loader.py            # CSV loading, mock data, KPI calculations
    ├── transaction_form.py       # Manual transaction entry (editable category)
    ├── category_memory.py        # Learns your corrections + custom categories
    ├── persistence.py            # Manual transactions, stored in users.db
    ├── auth.py                   # User accounts + password hashing
    ├── auth_ui.py                 # Login / signup / logout Streamlit UI
    └── password_strength.py       # Live password strength meter
```

Everything the app persists lives in the single `data/users.db` SQLite
file: user accounts, manually entered transactions, and learned category
corrections each get their own table.

**Guest mode is intentionally never persisted.** "guest" is one shared,
unauthenticated identity anyone can use without signing up, so writing its
data to `users.db` would mean every guest silently overwrites or mixes in
with every other guest's transactions and categories. Guest data lives
only in `st.session_state` for that browser session and disappears when it
ends — signing up is what gets you a private, durable account.

## Architecture

- **`core/db.py`** — The single shared SQLite connection (`data/users.db`).
  `auth.py`, `persistence.py`, and `category_memory.py` each create and
  query their own tables through this one connection function, so
  everything stays in one file.
- **`core/ml_engine.py`** — Trains a scikit-learn `Pipeline` (`TfidfVectorizer`
  + `LogisticRegression`) on a curated set of bank-description and everyday
  item patterns, cached across reruns with `st.cache_resource`. Exposes
  `classify_transaction()` (single description → `(category, confidence)`)
  and `categorize_dataframe()` (bulk). Checks a learned-overrides dict first,
  then the model, then falls back to keyword rules. `style_for_category()`
  gives every category — built-in or custom — a stable color/emoji.
- **`core/data_loader.py`** — Pure data-layer functions: CSV validation/
  loading, the 20-row mock dataset, cleaning/coercion, and KPI aggregation
  (`calculate_metrics`, `category_totals`, `monthly_totals`).
- **`core/category_memory.py`** — Remembers exact description → category
  corrections and any custom category names you've created, in two tables
  (`category_overrides`, `custom_categories`) keyed by username. No-ops for
  guests (see above).
- **`core/persistence.py`** — Stores each account's manually entered
  transactions in the `manual_transactions` table, keyed by username.
  No-ops for guests (see above).
- **`core/transaction_form.py`** — The manual-entry form. Suggests a
  category live as you type, lets you override via dropdown or a custom
  category, includes a per-row delete button, and remembers whatever you
  confirm.
- **`core/auth.py`** — User accounts, in the `users` table of `data/users.db`.
  Passwords are hashed with PBKDF2-HMAC-SHA256 and a unique per-user salt —
  never stored in plain text. Exposes `create_user()`, `verify_login()`,
  `username_exists()`, `is_valid_username()`, plus security-question-based
  password recovery (`get_security_question()`, `verify_security_answer()`,
  `reset_password()`) since there's no email integration to send reset
  links through.
- **`core/password_strength.py`** — A dependency-free heuristic scorer (0-4)
  used to drive the live strength meter on both signup and password reset.
- **`core/auth_ui.py`** — Login, Sign Up, and Forgot Password, switched
  between via link-style buttons ("Don't have an account? Sign Up",
  "Already have an account? Log In", "Forgot password?") rather than tabs —
  this also lets the app auto-redirect you to the login form (with a "your
  account was created" banner) right after signing up, instead of asking
  you to click over manually. Signup requires a unique username, full name,
  matching password/confirm fields, at least a "Fair" password strength
  score, and a security question + answer for later recovery. Each form is
  wrapped in `@st.fragment` so typing in it (e.g. updating the password
  strength meter) only reruns that form, not the whole page — a plain
  script rerun would otherwise re-execute the CSS, hero banner, and every
  import on every keystroke-triggered update. Also offers a **guest mode**
  (no account) for people who'd rather not sign up.
- **`app.py`** — Composes the above into the dashboard: the auth gate runs
  first, and only lightweight, stdlib-only modules (`core.auth_ui` →
  `core.auth`, `core.password_strength`) are imported before it. Heavier
  imports (pandas, scikit-learn, Plotly, the ML engine) are deferred until
  *after* login succeeds, so the login screen itself doesn't wait on them.
  Once past the gate: CSV upload and the manual entry form side-by-side,
  KPI metric cards, Plotly charts, and tabs for the transaction table and
  automated insights, all scoped to the logged-in account.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

You'll land on a login/signup screen. Sign up with a username, full name,
and password (the strength meter needs to show at least "Fair" before
signup is allowed), or click **"Continue without an account"** to try the
app in shared guest mode. No CSV on hand once you're in? A radio choice
next to the uploader lets you pick between the built-in 20-transaction mock
dataset or starting completely empty.

### About the "Deploy" button

Streamlit adds a **Deploy** button to the toolbar automatically whenever an
app runs on `localhost`. Clicking it only opens a wizard for publishing
*this app's code* to Streamlit Community Cloud (or shows deployment
instructions) — it does not install, copy, or run anything on any other
person's computer, and it does nothing at all unless you actively follow
through the publish flow. If you'd rather not see it (e.g. for a clean
recruiter-facing local demo), add a `.streamlit/config.toml` file:

```toml
[client]
toolbarMode = "viewer"
```

This hides the Deploy button (and the rerun/clear-cache developer options)
while still showing regular Streamlit is being used to end users.

### A note on `data/`

The `data/` folder is created automatically the first time someone signs
up, adds a transaction, or teaches the app a custom category — and it
contains exactly one file: `users.db`. It's local to your machine and
nothing is sent anywhere. Each account's data (transactions, category
corrections) is scoped to its own rows in that database by username, so
multiple people using the same deployed app don't see each other's
transactions or categories.

Guest mode is the one exception: transactions and corrections made while
"Continue without an account" is active are **never written to `users.db`
at all** — they exist only in that browser session's memory and vanish
when it ends. This is deliberate: "guest" is a single identity shared by
anyone who skips signup, so persisting it would mean every guest's data
mixes together. Signing up is what gets you a private, durable account.

### Future-dated transactions

Real bank statements only ever contain settled, historical transactions —
a future date almost always means a typo, a bad CSV export, or a
scheduled/pending payment that hasn't happened yet. The manual entry form
won't let you pick a date past today. Uploaded CSVs can't be blocked the
same way (it's someone else's file), so instead any future-dated rows are
flagged, shown in a dismissible warning for review, and excluded from
totals/charts by default — with a sidebar toggle to include them if you
decide they're legitimate.


## Real-world considerations before relying on this with real data

This was built to demonstrate the architecture and ML approach cleanly,
not as a production banking tool. A few gaps worth knowing about:

- **Real bank CSVs are messier than the mock data.** Actual exports often
  have noisy descriptions (`SQ *COFFEE SHOP 4421 XXXX`, truncated merchant
  codes, reference numbers), inconsistent date formats, and sometimes a
  different sign convention (some banks report expenses as positive with a
  separate debit/credit column). You'll likely need to extend
  `TRAINING_DATA`/`CATEGORY_KEYWORDS` in `core/ml_engine.py` and possibly
  `clean_transactions()` in `core/data_loader.py` for your bank's actual format.
- **Single currency assumption.** Everything is formatted and summed as a
  single `$` figure; a CSV mixing currencies would silently produce
  meaningless totals. There's no currency column or conversion logic.
- **No transfer/refund handling.** Moving money between your own accounts,
  or a refund reversing an earlier charge, will currently be counted as
  ordinary income/spend, which can distort totals if you track multiple
  accounts.
- **Accounts now exist, but auth is basic.** Passwords are hashed with
  PBKDF2-HMAC-SHA256 + a per-user salt (not stored in plain text), password
  recovery works via a security question (no email needed), and each
  account's data is isolated in its own database rows — real improvements
  over the earlier single-file version. Still missing for a production
  deployment: no login-attempt rate limiting/lockout, no session expiry,
  and SQLite isn't built for many concurrent writers — a real multi-tenant
  deployment would want `bcrypt`/`argon2` hashing, a proper database
  (Postgres, etc.), and HTTPS enforced at the hosting layer. A security
  question is also inherently weaker than email/SMS-based recovery (guessable
  answers, no second factor) — acceptable for a personal project, not for
  anything handling real financial accounts at scale.
- **Guest mode is intentionally not persisted at all.** Transactions and
  categories added in guest mode live only in that browser session and are
  gone once it ends — by design, since "guest" is one identity shared by
  anyone who skips signup. Fine for a quick look, not for anything you want
  to keep.
- **The classifier is trained on synthetic examples**, not a large labeled
  real-world dataset, so accuracy on unusual descriptions will be lower
  than a production model — this is where the category-memory/override
  system does a lot of the real work over time.

None of these block using it for personal, local, single-user tracking —
they're the kind of things to address before treating it as more than that.



