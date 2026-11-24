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
    Day,
    DayEntry,
    EntryTemplate,
    match_tab,
    month_layout,
    normalize_items,
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
    def _insert_rows(self, tab: str, after_row: int, date: dt.date, values: list[list[str]]) -> None:
        """Insert dated rows directly below ``after_row``, copying its formatting."""

    @abstractmethod
    def _delete_rows(self, tab: str, rows: list[int]) -> None:
        """Delete the given rows (1-based)."""

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

    def _month_items(self, year: int, month: int) -> dict[dt.date, list[DayEntry]]:
        """All rows of a month tab grouped by date (several rows = several projects that day)."""
        tab = self.find_tab(year, month)
        found: dict[dt.date, list[DayEntry]] = {}
        if not tab:
            return found
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
            if not d or d.year != year or d.month != month:
                continue
            previous = d
            found.setdefault(d, []).append(DayEntry(d, *cells[1:6], row=row_no))
        return found

    def get_month(self, year: int, month: int) -> list[Day]:
        """Every day of the month, in order. Days missing from the sheet come back empty."""
        found = self._month_items(year, month)
        days = [d for d in month_layout(year, month, spacers=False) if d]
        return [Day(d, found.get(d) or []) for d in days]

    def get_day(self, date: dt.date) -> Day:
        return Day(date, self._month_items(date.year, date.month).get(date) or [])

    def get_entry(self, date: dt.date) -> DayEntry:
        """The day's main row (first project)."""
        return self.get_day(date).primary

    def save_day(self, date: dt.date, items: list[DayEntry] | list[list[str]]) -> Day:
        """Replace everything logged on ``date`` with ``items`` (one row per project).

        The day's main row is updated in place; extra projects become extra rows
        directly below it, and rows no longer needed are removed. An empty list
        clears the day. Creates the month tab if needed.
        """
        values = normalize_items([i.values() if isinstance(i, DayEntry) else i for i in items])
        with self._lock:
            tab = self.find_tab(date.year, date.month)
            if not tab:
                tab = self._create_tab(date.year, date.month, None)
                self._tabs = None
            self._invalidate(tab)
            rows = sorted(i.row for i in self.get_day(date).items if i.row)
            wanted = values or [[""] * 5]
            if not rows:
                for v in wanted:
                    self._append_row(tab, date, v)
            else:
                keep = min(len(rows), len(wanted))
                self._write_rows(tab, {rows[k]: wanted[k] for k in range(keep)})
                if len(wanted) > len(rows):
                    self._insert_rows(tab, rows[-1], date, wanted[len(rows) :])
                elif len(rows) > len(wanted):
                    self._delete_rows(tab, rows[len(wanted) :])
            self._invalidate(tab)
            log.info("saved %d item(s) for %s in tab %s", len(values), date, tab)
            return self.get_day(date)

    def save_entry(self, entry: DayEntry) -> DayEntry:
        """Set the day to exactly this one entry (kept for single-project callers)."""
        day = self.save_day(entry.date, [entry] if entry.has_content or any(entry.values()) else [])
        entry.row = day.row
        return entry

    def clear_entry(self, date: dt.date) -> None:
        self.save_day(date, [])

    def fill_month(
        self,
        year: int,
        month: int,
        prefill: dict[dt.date, list],
        overwrite: bool = False,
    ) -> int:
        """Bulk-load days into a month (imports and templates).

        Each value is one row (``list[str]``) or several (``list[list[str]]``).
        Only empty days are filled unless ``overwrite`` is set. Returns the number
        of days written.
        """
        wanted = {d: normalize_items(v) for d, v in prefill.items()}
        wanted = {d: v for d, v in wanted.items() if v}
        if not wanted:
            return 0
        with self._lock:
            tab = self.find_tab(year, month)
            if not tab:
                self._create_tab(year, month, {d: v[0] for d, v in wanted.items()})
                self.refresh()
                for d, v in wanted.items():
                    if len(v) > 1:
                        self.save_day(d, v)
                return len(wanted)
            self._invalidate(tab)
            written = 0
            updates: dict[int, list[str]] = {}
            complex_days: dict[dt.date, list[list[str]]] = {}
            for day in self.get_month(year, month):
                values = wanted.get(day.date)
                if not values or (day.has_content and not overwrite):
                    continue
                rows = [i.row for i in day.items if i.row]
                if len(values) == 1 and len(rows) == 1:
                    updates[rows[0]] = values[0]  # fast path: batched single-row writes
                else:
                    complex_days[day.date] = values
                written += 1
            if updates:
                self._write_rows(tab, updates)
            self._invalidate(tab)
            for d, v in complex_days.items():
                self.save_day(d, v)
            return written

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
