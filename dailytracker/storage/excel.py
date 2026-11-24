"""Local ``.xlsx`` backend — for offline/local use and tests."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from copy import copy

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..model import month_layout, parse_tab_name, placeholder_values, tab_name
from . import style
from .base import RawRow, Storage, StorageError
from .style import MonthStyle


def _border(color: str) -> Border:
    side = Side(style="thin", color=color)
    return Border(left=side, right=side, top=side, bottom=side)


def set_text(cell, value) -> None:
    """Store text literally — never let user input become an Excel formula."""
    cell.value = value or None
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"


def style_month_sheet(
    ws, year: int, month: int, prefill: dict | None = None, look: MonthStyle | None = None
) -> None:
    """Lay out and style a month tab using the month template (default: the original design)."""
    prefill = prefill or {}
    look = look or MonthStyle()
    border = _border(look.border)
    ws.append(look.headers)
    ws.row_dimensions[1].height = style.HEADER_HEIGHT
    for col in range(1, 7):
        cell = ws.cell(row=1, column=col)
        cell.fill = PatternFill("solid", start_color=look.header_bg, end_color=look.header_bg)
        cell.font = Font(name=look.font, size=look.font_size, bold=True, color=look.header_fg)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    row = 2
    for d in month_layout(year, month, look.spacer_rows):
        if d is None:
            ws.row_dimensions[row].height = style.SPACER_HEIGHT
            row += 1
            continue
        bg, fg = look.colors(d.weekday())
        values = prefill.get(d) or placeholder_values(d, look.weekend_label)
        date_cell = ws.cell(row=row, column=1, value=d)
        date_cell.number_format = "mm/dd/yyyy"
        for offset, value in enumerate(values, start=2):
            set_text(ws.cell(row=row, column=offset), value)
        ws.row_dimensions[row].height = style.ROW_HEIGHT
        for col in range(1, 7):
            cell = ws.cell(row=row, column=col)
            cell.fill = PatternFill("solid", start_color=bg, end_color=bg)
            cell.font = Font(name=look.font, size=look.font_size, color=fg)
            cell.border = border
            cell.alignment = Alignment(
                vertical="center", horizontal="center" if col in (1, 6) else "left", wrap_text=col == 4
            )
        if look.merge_weekends and d.weekday() == 6 and row > 2 and ws.cell(row=row - 1, column=1).value:
            for col in range(3, 7):
                ws.merge_cells(start_row=row - 1, start_column=col, end_row=row, end_column=col)
                ws.cell(row=row - 1, column=col).alignment = Alignment(horizontal="center", vertical="center")
        row += 1

    for idx, width in enumerate(look.column_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"


class ExcelStorage(Storage):
    name = "excel"

    def __init__(self, path: str, cache_ttl: int = 60) -> None:
        super().__init__(cache_ttl)
        self.path = path

    # -------------------------------------------------------------- helpers

    def _load(self, data_only: bool = False, create: bool = False):
        if not os.path.exists(self.path):
            if not create:
                raise StorageError(f"Workbook {self.path} does not exist yet")
            wb = openpyxl.Workbook()
            wb.remove(wb.active)
            return wb
        try:
            return openpyxl.load_workbook(self.path, data_only=data_only)
        except Exception as exc:  # corrupted / locked file
            raise StorageError(f"Cannot open {self.path}: {exc}") from exc

    def _save(self, wb) -> None:
        """Atomic save: write to a temp file then swap, so a crash never corrupts the workbook."""
        # Keep the settings tab hidden (Excel needs at least one other visible sheet).
        if "_config" in wb.sheetnames and len(wb.sheetnames) > 1:
            wb["_config"].sheet_state = "hidden"
            if wb.active is not None and wb.active.title == "_config":
                wb.active = next(i for i, ws in enumerate(wb.worksheets) if ws.title != "_config")
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=directory)
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # --------------------------------------------------------------- hooks

    def _list_tabs(self) -> list[str]:
        if not os.path.exists(self.path):
            return []
        wb = self._load()
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()

    def _read_rows(self, tab: str) -> list[RawRow]:
        wb = self._load(data_only=True)
        try:
            ws = wb[tab]
            return [
                (idx, list(values))
                for idx, values in enumerate(ws.iter_rows(min_row=2, max_col=6, values_only=True), start=2)
            ]
        finally:
            wb.close()

    def _write_rows(self, tab: str, rows: dict[int, list[str]]) -> None:
        wb = self._load()
        ws = wb[tab]
        for row_no, values in rows.items():
            for offset, value in enumerate(values, start=2):
                cell = ws.cell(row=row_no, column=offset)
                if type(cell).__name__ == "MergedCell":
                    continue
                set_text(cell, value)
        self._save(wb)

    def _append_row(self, tab: str, date: dt.date, values: list[str]) -> int:
        wb = self._load()
        ws = wb[tab]
        row_no = ws.max_row + 1
        ws.cell(row=row_no, column=1, value=date).number_format = "mm/dd/yyyy"
        for offset, value in enumerate(values, start=2):
            set_text(ws.cell(row=row_no, column=offset), value)
        self._save(wb)
        return row_no

    def _insert_rows(self, tab: str, after_row: int, date: dt.date, values: list[list[str]]) -> None:
        wb = self._load()
        ws = wb[tab]
        count = len(values)
        ws.insert_rows(after_row + 1, amount=count)
        # openpyxl moves cells but not merged ranges or row heights; shift them ourselves.
        for rng in ws.merged_cells.ranges:
            if rng.min_row > after_row:
                rng.shift(0, count)
        heights = {r: ws.row_dimensions[r].height for r in range(after_row + 1, ws.max_row + 1)}
        for r in sorted(heights, reverse=True):
            ws.row_dimensions[r + count].height = heights[r]
        for offset, row_values in enumerate(values, start=1):
            r = after_row + offset
            ws.row_dimensions[r].height = ws.row_dimensions[after_row].height
            for col in range(1, 7):
                ws.cell(row=r, column=col)._style = copy(ws.cell(row=after_row, column=col)._style)
            ws.cell(row=r, column=1, value=date).number_format = "mm/dd/yyyy"
            for col, value in enumerate(row_values, start=2):
                set_text(ws.cell(row=r, column=col), value)
        self._save(wb)

    def _delete_rows(self, tab: str, rows: list[int]) -> None:
        wb = self._load()
        ws = wb[tab]
        for r in sorted(rows, reverse=True):
            for rng in list(ws.merged_cells.ranges):
                if rng.min_row <= r <= rng.max_row:
                    ws.unmerge_cells(str(rng))
            ws.delete_rows(r)
            for rng in ws.merged_cells.ranges:
                if rng.min_row > r:
                    rng.shift(0, -1)
        self._save(wb)

    def _create_tab(self, year: int, month: int, prefill) -> str:
        wb = self._load(create=True)
        name = tab_name(year, month)
        ws = wb.create_sheet(title=name)
        style_month_sheet(ws, year, month, prefill, self.month_style())
        # keep month tabs in chronological order, other tabs (Templates, _config) last
        wb._sheets.sort(key=lambda s: parse_tab_name(s.title) or (9999, 12))
        self._save(wb)
        return name

    def _read_meta(self, tab: str) -> list[list[str]]:
        if not os.path.exists(self.path):
            return []
        wb = self._load(data_only=True)
        try:
            if tab not in wb.sheetnames:
                return []
            return [
                list(r) for r in wb[tab].iter_rows(values_only=True) if any(c not in (None, "") for c in r)
            ]
        finally:
            wb.close()

    def _write_meta(self, tab: str, rows: list[list[str]], hidden: bool = False) -> None:
        wb = self._load(create=True)
        if tab in wb.sheetnames:
            del wb[tab]
        ws = wb.create_sheet(title=tab)
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                set_text(ws.cell(row=r, column=c), value)
        if rows:
            for c in range(1, len(rows[0]) + 1):
                ws.cell(row=1, column=c).font = Font(bold=True)
        self._save(wb)
