"""
core/password_strength.py
--------------------------
A lightweight, dependency-free password strength estimator for the signup
form's live meter.

This is a simple heuristic (length + character variety + a common-password
denylist), not a full attacker-cost model. It's good enough to nudge users
toward stronger passwords; for a production app, consider swapping this for
the `zxcvbn` library, which models realistic real-world guessing strategies
much more accurately.
"""

import re

_COMMON_PASSWORDS = {
    "password", "12345678", "123456789", "qwerty123", "letmein",
    "password1", "admin123", "welcome1", "abc12345", "iloveyou",
    "123123123", "qwertyuiop", "111111111",
}

# (score, label, color) for scores 0-4
_LEVELS = [
    (0, "Very Weak", "#ef4444"),
    (1, "Weak", "#f97316"),
    (2, "Fair", "#eab308"),
    (3, "Good", "#22c55e"),
    (4, "Strong", "#15803d"),
]


def password_strength(password: str) -> dict:
    """Score a password from 0 (very weak) to 4 (strong).

    Returns {"score": int, "label": str, "color": str, "feedback": [str, ...]}.
    """
    password = password or ""
    if not password:
        return {"score": 0, "label": "Very Weak", "color": _LEVELS[0][2], "feedback": ["Enter a password."]}

    if password.lower() in _COMMON_PASSWORDS:
        return {
            "score": 0,
            "label": "Very Weak",
            "color": _LEVELS[0][2],
            "feedback": ["This is one of the most commonly used passwords -- choose something less guessable."],
        }

    feedback = []
    score = 0

    if len(password) >= 8:
        score += 1
    else:
        feedback.append("Use at least 8 characters.")
    if len(password) >= 12:
        score += 1

    has_upper = bool(re.search(r"[A-Z]", password))
    has_lower = bool(re.search(r"[a-z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r"[^A-Za-z0-9]", password))
    variety = sum([has_upper, has_lower, has_digit, has_special])

    if variety >= 3:
        score += 1
    if variety == 4:
        score += 1

    if not has_upper:
        feedback.append("Add an uppercase letter.")
    if not has_lower:
        feedback.append("Add a lowercase letter.")
    if not has_digit:
        feedback.append("Add a number.")
    if not has_special:
        feedback.append("Add a special character (e.g. ! @ # $).")

    score = min(score, 4)
    _, label, color = _LEVELS[score]
    return {"score": score, "label": label, "color": color, "feedback": feedback}
