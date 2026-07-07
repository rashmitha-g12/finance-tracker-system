"""
core/auth_ui.py
-----------------
Streamlit UI for signup, login, logout, and password recovery.

`render_auth_gate()` renders a login/signup/forgot-password screen when no
one is logged in, and returns False so the caller (app.py) knows to stop
and not render the rest of the dashboard. Once someone logs in (or chooses
guest mode), it sets:

    st.session_state["authenticated"] = True
    st.session_state["username"]      = "their_username"
    st.session_state["full_name"]     = "Their Name"

Every other module that persists data (core/persistence.py,
core/category_memory.py) reads st.session_state["username"] to decide
*where* to save/load, so each account's financial data stays isolated.

Performance note: each form below is wrapped in @st.fragment. Without it,
every keystroke-triggered rerun (e.g. updating the password strength meter)
would re-execute the *entire* script -- imports, hero banner, CSS, all of
it. A fragment scopes that rerun to just the form itself, which is what
made the strength meter and page interactions feel slow before.
"""

import streamlit as st

from core.auth import (
    SECURITY_QUESTIONS,
    create_user,
    get_security_question,
    is_valid_username,
    reset_password,
    username_exists,
    verify_login,
    verify_security_answer,
)
from core.password_strength import password_strength

GUEST_USERNAME = "guest"


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated"))


def _set_mode(mode: str) -> None:
    """Switch which form is shown. Called from inside a fragment, so a full
    st.rerun() is needed to make the change visible outside that fragment."""
    st.session_state["auth_mode"] = mode
    st.rerun()


def _strength_meter(password: str) -> dict:
    strength = password_strength(password)
    if password:
        st.progress((strength["score"] + 1) / 5)
        st.markdown(
            f'Strength: <span style="color:{strength["color"]}; font-weight:700;">'
            f'{strength["label"]}</span>',
            unsafe_allow_html=True,
        )
        if strength["feedback"]:
            st.caption(" ".join(strength["feedback"]))
    return strength


@st.fragment
def _login_form() -> None:
    st.markdown("###### Log in to your account")
    username = st.text_input("Username", key="login_username", placeholder="Your username")
    password = st.text_input("Password", type="password", key="login_password", placeholder="Enter password")
    
    col_forgot = st.columns([3,1])
    with col_forgot[1]:
        if st.button("Forgot password?", type="tertiary"):
            _set_mode("forgot")
            
    st.write("")
    
    _, btn_center, _ = st.columns([1, 1.5, 1])
    with btn_center:
        login_clicked = st.button("Log In", use_container_width=True, type="primary")
        
    if login_clicked:
        if not username or not password:
            st.error("Please enter both a username and password.")
        else:
            success, message, full_name = verify_login(username, password)
            if success:
                st.session_state["authenticated"] = True
                st.session_state["username"] = username.strip()
                st.session_state["full_name"] = full_name
                st.rerun()
            else:
                st.error(message)
                
    st.write("")
    st.markdown("<p style='text-align:center; font-size:0.9rem; color:#6b7280; margin-bottom:0px;'>Don't have an account?</p>", unsafe_allow_html=True)
    _, link_center, _ = st.columns([1, 1.2, 1])
    with link_center:
        if st.button("Sign Up", type="tertiary", use_container_width=True):
            _set_mode("signup")

@st.fragment
def _signup_form() -> None:
    st.markdown("###### Create a new account")
    username = st.text_input(
        "Choose a username", key="signup_username",
        help="3-20 characters: letters, numbers, and underscores only.", placeholder="ex:'john_123'"
    )
    full_name = st.text_input("Full name", key="signup_full_name", placeholder="Enter Full Name")
    password = st.text_input("Password", type="password", key="signup_password", placeholder="Enter password")
    strength = _strength_meter(password)
    confirm_password = st.text_input("Confirm password", type="password", key="signup_confirm_password", placeholder="Retype password")
    
    st.markdown("###### Security question")
    st.caption("No email on file, so this is how you'll reset your password if you forget it.")
    security_question = st.selectbox("Choose a question", SECURITY_QUESTIONS, key="signup_security_question")
    security_answer = st.text_input(
        "Your answer", key="signup_security_answer", placeholder="Enter answer",
        help="Not case-sensitive. Pick something memorable that others couldn't easily guess.",
    )
    
    st.write("")
    _, btn_center, _ = st.columns([1, 1.5, 1])
    with btn_center:
        signup_clicked = st.button("Sign Up", use_container_width=True, type="primary")
        
    if signup_clicked:
        if not username or not full_name or not password or not confirm_password or not security_answer:
            st.error("Please fill in every field.")
        elif not is_valid_username(username):
            st.error("Username must be 3-20 characters: letters, numbers, and underscores only.")
        elif username_exists(username.strip()):
            st.error("That username is already taken.")
        elif password != confirm_password:
            st.error("Passwords don't match.")
        elif strength["score"] < 2:
            st.error("Please choose a stronger password (at least 'Fair') before continuing.")
        else:
            success, message = create_user(username, full_name, password, security_question, security_answer)
            if success:
                st.session_state["flash_message"] = "Account created! Please log in below."
                _set_mode("login")
            else:
                st.error(message)
                
    st.write("")
    st.markdown("<p style='text-align:center; font-size:0.9rem; color:#6b7280;margin-bottom:0px;'>Already have an account?</p>", unsafe_allow_html=True)
    _, link_center, _ = st.columns([1, 1.2, 1])
    with link_center:
        if st.button("Log In", type="tertiary", use_container_width=True):
            _set_mode("login")


@st.fragment
def _forgot_password_form() -> None:
    st.markdown("###### Reset your password")
    st.caption("No email needed -- answer your security question instead.")

    if "forgot_step" not in st.session_state:
        st.session_state["forgot_step"] = "find_account"

    if st.session_state["forgot_step"] == "find_account":
        username = st.text_input("Your username", key="forgot_username_input", placeholder="Enter username")
        if st.button("Find My Account", use_container_width=True, type="primary"):
            username = (username or "").strip()
            question = get_security_question(username) if username else None
            if not username:
                st.error("Please enter your username.")
            elif not question:
                st.error("No account found with that username and security question.")
            else:
                st.session_state["forgot_username"] = username
                st.session_state["forgot_question"] = question
                st.session_state["forgot_step"] = "answer_question"
                st.rerun(scope="fragment")
    else:
        st.info(f"🔒 {st.session_state['forgot_question']}")
        answer = st.text_input("Your answer", key="forgot_answer_input", placeholder="Enter answer")
        new_password = st.text_input("New password", type="password", key="forgot_new_password", placeholder="Enter password")
        strength = _strength_meter(new_password)
        confirm_new_password = st.text_input(
            "Confirm new password", type="password", key="forgot_confirm_password", placeholder="Retype password"
        )

        form_error=None
        col_reset, col_cancel = st.columns(2)
        with col_reset:
            if st.button("Reset Password", use_container_width=True, type="primary"):
                if not answer or not new_password or not confirm_new_password:
                    form_error="Please fill in every field."
                elif not verify_security_answer(st.session_state["forgot_username"], answer):
                    form_error="That answer doesn't match our records."
                elif new_password != confirm_new_password:
                    form_error="Passwords don't match."
                elif strength["score"] < 2:
                    form_error="Please choose a stronger password (at least 'Fair')."
                else:
                    reset_password(st.session_state["forgot_username"], new_password)
                    for key in ("forgot_step", "forgot_username", "forgot_question"):
                        st.session_state.pop(key, None)
                    st.session_state["flash_message"] = "Password reset! Please log in with your new password."
                    _set_mode("login")
        with col_cancel:
            if st.button("Cancel", use_container_width=True):
                for key in ("forgot_step", "forgot_username", "forgot_question"):
                    st.session_state.pop(key, None)
                _set_mode("login")

        if form_error:
            st.error(form_error)

    if st.button("← Back to Log In", type="tertiary"):
        for key in ("forgot_step", "forgot_username", "forgot_question"):
            st.session_state.pop(key, None)
        _set_mode("login")


def render_auth_gate() -> bool:
    """Render the login/signup/forgot-password screen. Returns True once
    someone is authenticated (including guest mode) so the caller can
    proceed; returns False otherwise (the caller should st.stop() right after)."""
    if is_authenticated():
        return True

    if "auth_mode" not in st.session_state:
        st.session_state["auth_mode"] = "login"

        
    left, center, right = st.columns([1, 1.4, 1])
    with center:
        st.markdown(
            "<h2 style='text-align:center; margin-bottom:0;'>💰 Welcome Back</h2>"
            "<p style='text-align:center; color:#6b7280; margin-top:0.3rem;'>"
            "Sign in to keep your transactions private, or continue as a guest.</p>",
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            if st.session_state.get("flash_message"):
                st.success(st.session_state.pop("flash_message"))

            mode = st.session_state["auth_mode"]
            if mode == "signup":
                _signup_form()
            elif mode == "forgot":
                _forgot_password_form()
            else:
                _login_form()

        st.write("")
        if st.button("Continue without an account (guest mode)", use_container_width=True):
            st.session_state["authenticated"] = True
            st.session_state["username"] = GUEST_USERNAME
            st.session_state["full_name"] = "Guest"
            st.rerun()
        st.markdown(
            "<p style='text-align:center; color:#9ca3af; font-size:0.85rem;'>"
            "Guest mode stores data locally under a single shared 'guest' profile "
            "-- it isn't private per-person, so anyone using guest mode on this "
            "install shares that data.</p>",
            unsafe_allow_html=True,
        )
    return False


def render_logout_button() -> None:
    """Show who's logged in and a logout control, in the sidebar."""
    if not is_authenticated():
        return
    with st.sidebar:
        st.markdown("---")
        st.caption(f"👤 Logged in as **{st.session_state.get('full_name', 'User')}**")
        if st.button("🚪 Log Out", use_container_width=True):
            from core import category_memory, transaction_form

            transaction_form.reset_session_cache()
            category_memory.reset_session_cache()
            for key in ("authenticated", "username", "full_name"):
                st.session_state.pop(key, None)
            st.rerun()
