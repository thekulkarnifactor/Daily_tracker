"""Daily Tracker — a calendar UI over a Google Sheet work log."""

from __future__ import annotations

import datetime as dt
import logging
import os

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Settings
from .storage import Storage, StorageError, build_storage

__version__ = "1.2.0"

csrf = CSRFProtect()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def create_app(settings: Settings | None = None, storage: Storage | None = None) -> Flask:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # python-dotenv is a dev-only convenience
        pass

    settings = settings or Settings()
    settings.validate()
    _configure_logging(os.environ.get("LOG_LEVEL", "INFO"))

    app = Flask(__name__)
    app.config.update(
        SETTINGS=settings,
        SECRET_KEY=settings.secret_key or os.urandom(32).hex(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.is_production,
        SESSION_COOKIE_NAME="dt_session",
        PERMANENT_SESSION_LIFETIME=dt.timedelta(days=14),
        PREFERRED_URL_SCHEME="https" if settings.is_production else "http",
        WTF_CSRF_TIME_LIMIT=None,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # history imports upload .xlsx files
    )
    # Render / Cloud Run terminate TLS at a proxy; trust its X-Forwarded-* headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config["STORAGE"] = storage or build_storage(settings)

    csrf.init_app(app)

    from .auth import init_auth
    from .import_views import bp as imp_bp
    from .templates_views import bp as tpl_bp
    from .views import bp as main_bp

    init_auth(app)
    app.register_blueprint(main_bp)
    app.register_blueprint(tpl_bp)
    app.register_blueprint(imp_bp)

    @app.context_processor
    def inject_globals():
        return {"app_version": __version__}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' https://*.googleusercontent.com data:; "
            "style-src 'self'; "
            "script-src 'self'; form-action 'self' https://accounts.google.com; "
            "frame-ancestors 'none'; base-uri 'self'",
        )
        if settings.is_production:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.errorhandler(StorageError)
    def storage_error(exc):
        app.logger.error("storage error: %s", exc)
        return render_template("error.html", code=503, title="Sheet unavailable", message=str(exc)), 503

    @app.errorhandler(CSRFError)
    def csrf_error(exc):
        return render_template(
            "error.html", code=400, title="Session expired", message="Reload the page and try again."
        ), 400

    for code, title in (
        (400, "Bad request"),
        (404, "Not found"),
        (405, "Not allowed"),
        (413, "File too large"),
        (500, "Something went wrong"),
    ):

        def handler(exc, code=code, title=title):
            message = getattr(exc, "description", "") if code != 500 else "Please try again."
            return render_template("error.html", code=code, title=title, message=message), code

        app.register_error_handler(code, handler)

    return app
