"""Google sign-in restricted to an allow-list of email addresses."""

from __future__ import annotations

import functools
import logging

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)
oauth = OAuth()

GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"


def init_auth(app) -> None:
    settings = app.config["SETTINGS"]
    oauth.init_app(app)
    if not settings.auth_disabled:
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url=GOOGLE_DISCOVERY,
            client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
        )
    app.register_blueprint(bp)


def current_user() -> dict | None:
    if current_app.config["SETTINGS"].auth_disabled:
        return {"email": "local@dev", "name": "Local dev", "picture": ""}
    return session.get("user")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target: str | None) -> str:
    # Only allow same-site relative paths to prevent open redirects.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


@bp.get("/login")
def login():
    if current_user():
        return redirect(_safe_next(request.args.get("next")))
    session["next"] = _safe_next(request.args.get("next"))
    return render_template("login.html")


@bp.post("/login/google")
def login_google():
    redirect_uri = url_for("auth.callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.get("/auth/callback")
def callback():
    settings = current_app.config["SETTINGS"]
    try:
        token = oauth.google.authorize_access_token()
    except Exception:  # state mismatch, user cancelled, etc.
        log.warning("Google sign-in failed", exc_info=True)
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or email not in settings.allowed_emails:
        log.warning("Rejected sign-in for %s", email or "<unknown>")
        flash("This Google account is not allowed to use Daily Tracker.", "error")
        return redirect(url_for("auth.login"))

    next_url = session.pop("next", None)
    session.clear()
    session.permanent = True
    session["user"] = {"email": email, "name": info.get("name", email), "picture": info.get("picture", "")}
    log.info("Signed in %s", email)
    return redirect(_safe_next(next_url))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
