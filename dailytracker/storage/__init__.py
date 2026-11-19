from __future__ import annotations

from ..config import Settings, load_service_account_info
from .base import Storage, StorageError


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "excel":
        from .excel import ExcelStorage

        return ExcelStorage(settings.excel_path, cache_ttl=settings.cache_ttl_seconds)

    from .sheets import SheetsStorage

    return SheetsStorage(
        settings.google_sheet_id,
        load_service_account_info() or {},
        cache_ttl=settings.cache_ttl_seconds,
    )


__all__ = ["Storage", "StorageError", "build_storage"]
