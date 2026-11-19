import datetime as dt

import pytest

from dailytracker import create_app
from dailytracker.config import Settings
from dailytracker.storage.excel import ExcelStorage


@pytest.fixture
def excel_path(tmp_path):
    return str(tmp_path / "Daily.xlsx")


@pytest.fixture
def storage(excel_path):
    return ExcelStorage(excel_path, cache_ttl=0)


def make_settings(**overrides) -> Settings:
    base = dict(
        env="development",
        secret_key="x" * 40,
        storage_backend="excel",
        excel_path="unused.xlsx",
        auth_disabled=True,
        google_client_id="",
        google_client_secret="",
        allowed_emails=[],
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def app(storage):
    app = create_app(make_settings(), storage=storage)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def weekday():
    return dt.date(2026, 11, 17)  # a Tuesday
