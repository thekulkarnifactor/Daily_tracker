"""Storage abstraction shared by the Google Sheets and Excel backends.

A backend only has to know how to list tabs, read raw rows, write rows and
create a styled month tab. Everything else (date matching, caching, building
``DayEntry`` objects, upserts) lives here so both backends behave the same.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from abc import ABC, abstractmethod

from ..model import (
    TEMPLATE_HEADERS,
    DayEntry,
    EntryTemplate,
    match_tab,
    month_layout,
    parse_date,
    parse_tab_name,
    shift_month,
)
from .style import MonthStyle

log = logging.getLogger(__name__)

RawRow = tuple[int, list]  # (1-based row number, [A, B, C, D, E, F])

TEMPLATES_TAB = "Templates"  # visible: editable straight in the sheet too
CONFIG_TAB = "_config"  # hidden: key/value app settings (month template)


class StorageError(RuntimeError):
    """Raised when the backing spreadsheet can't be read or written."""


class Storage(ABC):
    name = "base"

    def __init__(self, cache_ttl: int = 60) -> None:
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, list[RawRow]]] = {}
        self._tabs: tuple[float, list[str]] | None = None
        self._meta_cache: dict[str, tuple[float, list[list[str]]]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ backend hooks

    @abstractmethod
    def _list_tabs(self) -> list[str]: ...

    @abstractmethod
    def _read_rows(self, tab: str) -> list[RawRow]: ...

    @abstractmethod
    def _write_rows(self, tab: str, rows: dict[int, list[str]]) -> None:
        """Write columns B..F for each row number."""

    @abstractmethod
    def _append_row(self, tab: str, date: dt.date, values: list[str]) -> int:
        """Append a dated row to the bottom of a tab and return its row number."""

    @abstractmethod
    def _create_tab(self, year: int, month: int, prefill: dict[dt.date, list[str]] | None) -> str: ...

    @abstractmethod
    def _read_meta(self, tab: str) -> list[list[str]]:
        """All values of a non-month tab as text ([] if the tab doesn't exist)."""

    @abstractmethod
    def _write_meta(self, tab: str, rows: list[list[str]], hidden: bool = False) -> None:
        """Replace the whole content of a non-month tab, creating it if needed."""

    def ping(self) -> None:
        """Raise if the backend is unreachable."""
        self._list_tabs()

    # ------------------------------------------------------------------ caching

    def refresh(self) -> None:
        with self._lock:
            self._cache.clear()
            self._meta_cache.clear()
            self._tabs = None

    def list_tabs(self) -> list[str]:
        with self._lock:
            if self._tabs and time.monotonic() - self._tabs[0] < self._cache_ttl:
                return self._tabs[1]
            tabs = self._list_tabs()
            self._tabs = (time.monotonic(), tabs)
            return tabs

    def _rows(self, tab: str) -> list[RawRow]:
        with self._lock:
            hit = self._cache.get(tab)
            if hit and time.monotonic() - hit[0] < self._cache_ttl:
                return hit[1]
            rows = self._read_rows(tab)
            self._cache[tab] = (time.monotonic(), rows)
            return rows

    def _invalidate(self, tab: str) -> None:
        with self._lock:
            self._cache.pop(tab, None)

    # ------------------------------------------------------------------- public

    def find_tab(self, year: int, month: int) -> str | None:
        return match_tab(self.list_tabs(), year, month)

    def get_month(self, year: int, month: int) -> list[DayEntry]:
        """Every day of the month, in order. Days missing from the sheet come back empty."""
        tab = self.find_tab(year, month)
        found: dict[dt.date, DayEntry] = {}
        if tab:
            previous: dt.date | None = None
            for row_no, cells in self._rows(tab):
                cells = (list(cells) + [""] * 6)[:6]
                d = parse_date(cells[0], year, month)
                if d is None and previous and any(str(c or "").strip() for c in cells[1:]):
                    # A row with content but a blank date cell, sitting right after a
                    # dated row (seen in older sheets) belongs to the following day.
                    candidate = previous + dt.timedelta(days=1)
                    if candidate.month == month and candidate not in found:
                        d = candidate
                if not d or d.year != year or d.month != month or d in found:
                    continue
                previous = d
                found[d] = DayEntry(d, *cells[1:6], row=row_no)
        days = [d for d in month_layout(year, month, spacers=False) if d]
        return [found.get(d) or DayEntry(d) for d in days]

    def get_entry(self, date: dt.date) -> DayEntry:
        for entry in self.get_month(date.year, date.month):
            if entry.date == date:
                return entry
        return DayEntry(date)

    def save_entry(self, entry: DayEntry) -> DayEntry:
        """Insert or update the row for ``entry.date``; creates the month tab if needed."""
        with self._lock:
            year, month = entry.date.year, entry.date.month
            tab = self.find_tab(year, month)
            if not tab:
                tab = self._create_tab(year, month, None)
                self._tabs = None
            self._invalidate(tab)
            current = self.get_entry(entry.date)
            if current.row:
                self._write_rows(tab, {current.row: entry.values()})
                entry.row = current.row
            else:
                entry.row = self._append_row(tab, entry.date, entry.values())
            self._invalidate(tab)
            log.info("saved entry for %s in tab %s (row %s)", entry.date, tab, entry.row)
            return entry

    def clear_entry(self, date: dt.date) -> None:
        self.save_entry(DayEntry(date))

    def fill_month(
        self,
        year: int,
        month: int,
        prefill: dict[dt.date, list[str]],
        overwrite: bool = False,
    ) -> int:
        """Bulk-load values into a month (used by the import script).

        Only empty days are filled unless ``overwrite`` is set. Returns the
        number of rows written.
        """
        with self._lock:
            tab = self.find_tab(year, month)
            if not tab:
                self._create_tab(year, month, prefill)
                self.refresh()
                return len(prefill)
            self._invalidate(tab)
            appended = 0
            updates: dict[int, list[str]] = {}
            for entry in self.get_month(year, month):
                values = prefill.get(entry.date)
                if not values or not any(values):
                    continue
                if entry.has_content and not overwrite:
                    continue
                if entry.row:
                    updates[entry.row] = values
                else:
                    self._append_row(tab, entry.date, values)
                    appended += 1
            if updates:
                self._write_rows(tab, updates)
            self._invalidate(tab)
            return len(updates) + appended

    def available_months(self, start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
        """Months between start and end, plus any month that already has a tab."""
        months: set[tuple[int, int]] = set()
        cur = start
        while cur <= end:
            months.add(cur)
            cur = shift_month(*cur, 1)
        try:
            for name in self.list_tabs():
                parsed = parse_tab_name(name)
                if parsed:
                    months.add(parsed)
        except StorageError:
            log.exception("could not list tabs")
        return sorted(months)

    # ------------------------------------------------------------ meta tabs

    def _meta(self, tab: str) -> list[list[str]]:
        with self._lock:
            hit = self._meta_cache.get(tab)
            if hit and time.monotonic() - hit[0] < self._cache_ttl:
                return hit[1]
            rows = [[("" if c is None else str(c)) for c in row] for row in self._read_meta(tab)]
            self._meta_cache[tab] = (time.monotonic(), rows)
            return rows

    def _put_meta(self, tab: str, rows: list[list[str]], hidden: bool = False) -> None:
        with self._lock:
            self._write_meta(tab, rows, hidden)
            self._meta_cache.pop(tab, None)
            self._tabs = None

    # ------------------------------------------------------- entry templates

    def list_templates(self) -> list[EntryTemplate]:
        rows = self._meta(TEMPLATES_TAB)
        templates: list[EntryTemplate] = []
        seen: set[str] = set()
        for row in rows[1:]:
            cells = (list(row) + [""] * 6)[:6]
            t = EntryTemplate(*cells)
            if t.name and t.name.lower() not in seen:
                seen.add(t.name.lower())
                templates.append(t)
        return templates

    def get_template(self, name: str) -> EntryTemplate | None:
        key = (name or "").strip().lower()
        return next((t for t in self.list_templates() if t.name.lower() == key), None)

    def save_template(self, template: EntryTemplate, original_name: str | None = None) -> None:
        """Create or update a template (matched by name, case-insensitive). Supports renaming."""
        if not template.name:
            raise ValueError("Template name is required")
        replace = {template.name.lower(), (original_name or "").strip().lower()} - {""}
        with self._lock:
            kept = [t for t in self.list_templates() if t.name.lower() not in replace]
            self._store_templates(sorted([*kept, template], key=lambda t: t.name.lower()))

    def delete_template(self, name: str) -> bool:
        with self._lock:
            templates = self.list_templates()
            kept = [t for t in templates if t.name.lower() != (name or "").strip().lower()]
            if len(kept) == len(templates):
                return False
            self._store_templates(kept)
            return True

    def _store_templates(self, templates: list[EntryTemplate]) -> None:
        self._put_meta(TEMPLATES_TAB, [TEMPLATE_HEADERS, *[[t.name, *t.values()] for t in templates]])

    def apply_template(
        self, template: EntryTemplate, dates: list[dt.date], overwrite: bool = False
    ) -> tuple[int, int]:
        """Write a template into many days (weekends are skipped). Returns (written, skipped)."""
        workdays = sorted({d for d in dates if d.weekday() < 5})
        by_month: dict[tuple[int, int], dict[dt.date, list[str]]] = {}
        for d in workdays:
            by_month.setdefault((d.year, d.month), {})[d] = template.values()
        written = 0
        for (year, month), prefill in sorted(by_month.items()):
            written += self.fill_month(year, month, prefill, overwrite=overwrite)
        return written, len(workdays) - written

    # -------------------------------------------------------- month template

    def _config(self) -> dict[str, str]:
        return {row[0]: row[1] for row in self._meta(CONFIG_TAB) if len(row) >= 2 and row[0]}

    def month_style(self) -> MonthStyle:
        try:
            return MonthStyle.from_json(self._config().get("month_style"))
        except StorageError:
            log.exception("could not read month template; using defaults")
            return MonthStyle()

    def save_month_style(self, style: MonthStyle | None) -> None:
        """Save the month template (``None`` resets to the original design)."""
        with self._lock:
            config = self._config()
            if style is None:
                config.pop("month_style", None)
            else:
                config["month_style"] = style.validate().to_json()
            self._put_meta(
                CONFIG_TAB, [["key", "value"], *[[k, v] for k, v in sorted(config.items())]], hidden=True
            )

    def create_month(self, year: int, month: int) -> str:
        """Create a month tab now (using the month template) if it doesn't exist yet."""
        with self._lock:
            tab = self.find_tab(year, month)
            if tab:
                return tab
            tab = self._create_tab(year, month, None)
            self._tabs = None
            return tab
