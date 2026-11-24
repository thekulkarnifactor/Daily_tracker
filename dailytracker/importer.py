"""Import day entries from an Excel workbook (e.g. an old Daily.xlsx) into storage.

Used by the "Import history" page and by ``scripts/import_excel.py``.
The flow is two-step: ``analyze`` compares the file with what is already in the
sheet (nothing is written), then ``run_import`` writes only what was chosen.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .model import DayEntry, parse_tab_name
from .storage import Storage, StorageError
from .storage.excel import ExcelStorage

Month = tuple[int, int]
MonthDays = dict[Month, dict[dt.date, list[str]]]

UPLOAD_TTL_SECONDS = 2 * 60 * 60
_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "dailytracker-imports")


class ImportFileError(ValueError):
    """The uploaded file can't be read as a Daily workbook."""


def read_workbook(path: str) -> tuple[MonthDays, list[str]]:
    """All non-empty day entries in a workbook, grouped by month, plus skipped tab names."""
    if not os.path.exists(path):
        raise ImportFileError(f"File not found: {path}")
    source = ExcelStorage(path, cache_ttl=0)
    months: MonthDays = defaultdict(dict)
    skipped: list[str] = []
    try:
        tabs = source.list_tabs()
    except StorageError as exc:
        raise ImportFileError("This file isn't a readable .xlsx workbook.") from exc
    for name in tabs:
        ym = parse_tab_name(name)
        if not ym:
            skipped.append(name)
            continue
        for entry in source.get_month(*ym):
            if entry.has_content:
                months[ym][entry.date] = entry.values()
    return dict(months), skipped


def _norm(values: list[str]) -> tuple[str, ...]:
    return tuple(" ".join(str(v or "").split()).lower() for v in values)


@dataclass
class MonthPlan:
    year: int
    month: int
    tab: str | None  # existing tab in the target, or None if it will be created
    new: list[str] = field(default_factory=list)  # ISO dates empty in the target
    conflicts: list[dict] = field(default_factory=list)  # target has different content
    same: int = 0

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def label(self) -> str:
        return dt.date(self.year, self.month, 1).strftime("%b %Y")

    @property
    def total(self) -> int:
        return len(self.new) + len(self.conflicts) + self.same


def analyze(source: MonthDays, target: Storage) -> list[MonthPlan]:
    """Compare file contents with the target sheet. Read-only."""
    plans: list[MonthPlan] = []
    for year, month in sorted(source):
        days = source[(year, month)]
        tab = target.find_tab(year, month)
        existing = {e.date: e for e in target.get_month(year, month)} if tab else {}
        plan = MonthPlan(year, month, tab)
        for d in sorted(days):
            values = days[d]
            current: DayEntry | None = existing.get(d)
            if not current or not current.has_content:
                plan.new.append(d.isoformat())
            elif _norm(current.values()) == _norm(values):
                plan.same += 1
            else:
                plan.conflicts.append(
                    {
                        "date": d.isoformat(),
                        "file": " / ".join(v for v in values[:3] if v)[:120],
                        "sheet": " / ".join(v for v in current.values()[:3] if v)[:120],
                    }
                )
        plans.append(plan)
    return plans


def run_import(
    source: MonthDays, target: Storage, months: set[Month], overwrite: bool = False
) -> tuple[int, int]:
    """Write chosen months. Returns (days written, months touched).

    Without ``overwrite`` only days that are empty in the sheet are filled.
    Days whose content is already identical are never rewritten.
    """
    written = touched = 0
    for ym in sorted(months & set(source)):
        plan = analyze({ym: source[ym]}, target)[0]
        chosen = set(plan.new) | ({c["date"] for c in plan.conflicts} if overwrite else set())
        if not chosen:
            continue
        prefill = {d: v for d, v in source[ym].items() if d.isoformat() in chosen}
        written += target.fill_month(*ym, prefill, overwrite=overwrite)
        touched += 1
    return written, touched


# --------------------------------------------------------- staged uploads (web)


def stage_upload(source: MonthDays, filename: str) -> str:
    """Keep a parsed upload server-side between preview and import; returns a token."""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    _cleanup()
    token = secrets.token_urlsafe(16)
    payload = {
        "filename": filename,
        "months": {
            f"{y:04d}-{m:02d}": {d.isoformat(): v for d, v in days.items()} for (y, m), days in source.items()
        },
    }
    with open(os.path.join(_UPLOAD_DIR, f"{token}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return token


def load_staged(token: str) -> tuple[MonthDays, str] | None:
    if not token or not token.replace("-", "").replace("_", "").isalnum():
        return None
    path = os.path.join(_UPLOAD_DIR, f"{token}.json")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > UPLOAD_TTL_SECONDS:
        return None
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    months: MonthDays = {}
    for key, days in payload["months"].items():
        y, m = map(int, key.split("-"))
        months[(y, m)] = {dt.date.fromisoformat(d): v for d, v in days.items()}
    return months, payload.get("filename", "upload.xlsx")


def discard_staged(token: str) -> None:
    path = os.path.join(_UPLOAD_DIR, f"{token}.json")
    if os.path.exists(path):
        os.remove(path)


def _cleanup() -> None:
    now = time.time()
    for name in os.listdir(_UPLOAD_DIR):
        path = os.path.join(_UPLOAD_DIR, name)
        try:
            if now - os.path.getmtime(path) > UPLOAD_TTL_SECONDS:
                os.remove(path)
        except OSError:
            pass
