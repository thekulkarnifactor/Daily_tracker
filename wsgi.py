"""WSGI entry point: ``gunicorn wsgi:app`` (production) or ``python wsgi.py`` (local)."""

import os

from dailytracker import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("APP_ENV") != "production",
    )
