import datetime as dt

import pytest

from dailytracker import create_app
from tests.conftest import make_settings


def test_dashboard_renders(client):
    resp = client.get("/?month=2026-11")
    assert resp.status_code == 200
    assert b"November 2026" in resp.data
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]


def test_legacy_sheet_param(client):
    assert b"September 2023" in client.get("/?sheet=Sept-23").data


def test_save_and_clear_flow(client, storage, weekday):
    resp = client.post(
        "/entry",
        data={
            "date": weekday.isoformat(),
            "project": "EZ Jobs",
            "category": "Core Dev - Coding",
            "details": "<script>alert(1)</script>",
            "assignee": "Lead",
            "status": "Done",
        },
    )
    assert resp.status_code == 302
    assert storage.get_entry(weekday).status == "Done"

    page = client.get("/?month=2026-11").data
    assert b"<script>alert(1)</script>" not in page  # escaped
    assert b"&lt;script&gt;" in page

    client.post("/entry/clear", data={"date": weekday.isoformat()})
    assert not storage.get_entry(weekday).has_content


def test_weekend_and_bad_input_rejected(client):
    assert client.post("/entry", data={"date": "2026-11-21", "project": "x"}).status_code == 400
    assert client.post("/entry", data={"date": "nope", "project": "x"}).status_code == 400


def test_project_required(client, storage, weekday):
    client.post("/entry", data={"date": weekday.isoformat(), "project": "  "})
    assert not storage.get_entry(weekday).has_content


def test_api_and_export(client, storage, weekday):
    client.post("/entry", data={"date": weekday.isoformat(), "project": "P", "status": "Done"})
    data = client.get("/api/month/2026-11").get_json()
    assert data["summary"]["done"] == 1
    assert len(data["entries"]) == 30
    csv = client.get("/export/2026-11.csv")
    assert csv.mimetype == "text/csv" and b"2026-11-17,P" in csv.data


def test_health(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_csrf_enforced(storage, weekday):
    app = create_app(make_settings(), storage=storage)
    app.config.update(TESTING=True)
    resp = app.test_client().post("/entry", data={"date": weekday.isoformat(), "project": "x"})
    assert resp.status_code == 400
    assert not storage.get_entry(weekday).has_content


# ------------------------------------------------------------------ auth


@pytest.fixture
def auth_app(storage):
    settings = make_settings(
        auth_disabled=False,
        google_client_id="id",
        google_client_secret="secret",
        allowed_emails=["harish@example.com"],
    )
    app = create_app(settings, storage=storage)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


def test_requires_login(auth_app):
    resp = auth_app.test_client().get("/")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert auth_app.test_client().get("/healthz").status_code == 200


def _fake_callback(monkeypatch, email, verified=True):
    from dailytracker import auth

    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": {"email": email, "email_verified": verified, "name": "H"}},
    )


def test_allowed_email_signs_in(auth_app, monkeypatch):
    _fake_callback(monkeypatch, "Harish@Example.com")
    c = auth_app.test_client()
    assert c.get("/auth/callback").status_code == 302
    assert c.get("/?month=2026-11").status_code == 200
    c.post("/logout")
    assert c.get("/").status_code == 302


@pytest.mark.parametrize("email,verified", [("someone@else.com", True), ("harish@example.com", False)])
def test_other_emails_rejected(auth_app, monkeypatch, email, verified):
    _fake_callback(monkeypatch, email, verified)
    c = auth_app.test_client()
    c.get("/auth/callback")
    assert c.get("/").status_code == 302


def test_open_redirect_blocked(auth_app):
    from dailytracker.auth import _safe_next

    with auth_app.test_request_context():
        assert _safe_next("//evil.com") == "/"
        assert _safe_next("https://evil.com") == "/"
        assert _safe_next("/?month=2026-11") == "/?month=2026-11"


def test_production_config_validation():
    with pytest.raises(RuntimeError, match="AUTH_DISABLED"):
        make_settings(env="production").validate()
    with pytest.raises(RuntimeError, match="GOOGLE_SHEET_ID"):
        make_settings(storage_backend="sheets").validate()
    make_settings(
        env="production",
        auth_disabled=False,
        google_client_id="a",
        google_client_secret="b",
        allowed_emails=["x@y.z"],
    ).validate()


def test_today_marker(client, monkeypatch):
    from dailytracker import views

    monkeypatch.setattr(views, "today", lambda: dt.date(2026, 11, 19))
    assert b"is-today" in client.get("/").data


def test_login_page_renders(auth_app):
    resp = auth_app.test_client().get("/login")
    assert resp.status_code == 200 and b"Continue with Google" in resp.data


def test_get_on_form_urls_redirects_home(client):
    for url in ("/entry", "/entry/clear", "/sync"):
        resp = client.get(url)
        assert resp.status_code == 302 and resp.headers["Location"].endswith("/")


def test_unauthenticated_post_returns_to_dashboard_after_login(auth_app):
    resp = auth_app.test_client().post("/entry", data={"date": "2026-11-17", "project": "x"})
    assert "next=/" in resp.headers["Location"] and "entry" not in resp.headers["Location"]
