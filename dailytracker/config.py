"""Application configuration, loaded from environment variables.

Every setting can be supplied through the environment (or a local ``.env`` file
in development). See ``.env.example`` for the full list.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def load_service_account_info() -> dict | None:
    """Return service-account credentials as a dict, or None if not configured.

    Accepts either ``GOOGLE_SERVICE_ACCOUNT_JSON`` (raw JSON or base64-encoded
    JSON) or ``GOOGLE_APPLICATION_CREDENTIALS`` (path to a JSON key file).
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        if not raw.startswith("{"):
            raw = base64.b64decode(raw).decode("utf-8")
        return json.loads(raw)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))

    # Storage
    storage_backend: str = field(default_factory=lambda: os.environ.get("STORAGE_BACKEND", "sheets").lower())
    google_sheet_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_SHEET_ID", ""))
    excel_path: str = field(default_factory=lambda: os.environ.get("EXCEL_PATH", "Daily.xlsx"))
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.environ.get("CACHE_TTL_SECONDS", "60")))

    # Timeline shown in the month picker
    timeline_start: str = field(default_factory=lambda: os.environ.get("TIMELINE_START", "2023-07"))
    timeline_months_ahead: int = field(
        default_factory=lambda: int(os.environ.get("TIMELINE_MONTHS_AHEAD", "6"))
    )
    timezone: str = field(default_factory=lambda: os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))

    # Auth
    auth_disabled: bool = field(default_factory=lambda: _bool("AUTH_DISABLED"))
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    allowed_emails: list[str] = field(default_factory=lambda: _csv("ALLOWED_EMAILS"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        """Fail fast on misconfiguration instead of failing on the first request."""
        problems: list[str] = []
        if self.is_production:
            if not self.secret_key or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to at least 32 random characters")
            if self.auth_disabled:
                problems.append("AUTH_DISABLED cannot be used when APP_ENV=production")
        if not self.auth_disabled:
            if not (self.google_client_id and self.google_client_secret):
                problems.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
            if not self.allowed_emails:
                problems.append("ALLOWED_EMAILS must list at least one email address")
        if self.storage_backend == "sheets" and not self.google_sheet_id:
            problems.append("GOOGLE_SHEET_ID is required when STORAGE_BACKEND=sheets")
        if self.storage_backend not in {"sheets", "excel"}:
            problems.append("STORAGE_BACKEND must be 'sheets' or 'excel'")
        if problems:
            raise RuntimeError("Invalid configuration:\n  - " + "\n  - ".join(problems))
