"""Verify configuration and Google Sheet access before deploying.

python -m scripts.check_setup
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailytracker.config import Settings, load_service_account_info  # noqa: E402
from dailytracker.storage import StorageError, build_storage  # noqa: E402


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    settings = Settings()
    ok = True
    try:
        settings.validate()
        print("✓ configuration looks valid")
    except RuntimeError as exc:
        print(f"✗ {exc}")
        ok = False

    if settings.storage_backend == "sheets":
        info = load_service_account_info()
        if not info:
            print("✗ no service account credentials (GOOGLE_SERVICE_ACCOUNT_JSON)")
            return 1
        print(f"✓ service account: {info.get('client_email')}")
        print("  → the Google Sheet must be shared with this address as Editor")

    try:
        storage = build_storage(settings)
        tabs = storage.list_tabs()
        preview = ", ".join(tabs[:8]) + (" …" if len(tabs) > 8 else "")
        print(f"✓ storage reachable ({storage.name}); {len(tabs)} tab(s): {preview}")
    except StorageError as exc:
        print(f"✗ {exc}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
