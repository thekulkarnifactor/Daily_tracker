"""Local ``.xlsx`` backend — for offline/local use and tests."""

from __future__ import annotations

import datetime as dt
import os
import tempfile

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..model import HEADERS, month_layout, placeholder_values, tab_name
from . import style
from .base import RawRow, Storage, StorageError


def _border() -> Border:
    side = Side(style="thin", color=style.BORDER)
    return Border(left=side, right=side, top=side, bottom=side)


def set_text(cell, value) -> None:
    """Store text literally — never let user input become an Excel formula."""
    cell.value = value or None
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"


def style_month_sheet(ws, year: int, month: int, prefill: dict | None = None) -> None:
    """Lay out and style a month tab exactly like the original workbook."""
    prefill = prefill or {}
    border = _border()
    ws.append(HEADERS)
    ws.row_dimensions[1].height = style.HEADER_HEIGHT
    for col in range(1, 7):
        cell = ws.cell(row=1, column=col)
        cell.fill = PatternFill("solid", start_color=style.HEADER_BG, end_color=style.HEADER_BG)
        cell.font = Font(name="Calibri", size=11, bold=True, color=style.HEADER_FG)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    row = 2
    for d in month_layout(year, month):
        if d is None:
            ws.row_dimensions[row].height = style.SPACER_HEIGHT
            row += 1
            continue
        bg, fg = style.WEEKDAY_COLORS[d.weekday()]
        values = prefill.get(d) or placeholder_values(d)
        date_cell = ws.cell(row=row, column=1, value=d)
        date_cell.number_format = "mm/dd/yyyy"
        for offset, value in enumerate(values, start=2):
            set_text(ws.cell(row=row, column=offset), value)
        ws.row_dimensions[row].height = style.ROW_HEIGHT
        for col in range(1, 7):
            cell = ws.cell(row=row, column=col)
            cell.fill = PatternFill("solid", start_color=bg, end_color=bg)
            cell.font = Font(name="Calibri", size=11, color=fg)
            cell.border = border
            cell.alignment = Alignment(
                vertical="center", horizontal="center" if col in (1, 6) else "left", wrap_text=col == 4
            )
        if d.weekday() == 6 and row > 2 and ws.cell(row=row - 1, column=1).value:
            for col in range(3, 7):
                ws.merge_cells(start_row=row - 1, start_column=col, end_row=row, end_column=col)
                ws.cell(row=row - 1, column=col).alignment = Alignment(horizontal="center", vertical="center")
        row += 1

    for idx, width in enumerate(style.COLUMN_WIDTHS, start=1):
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

    def _create_tab(self, year: int, month: int, prefill) -> str:
        wb = self._load(create=True)
        name = tab_name(year, month)
        ws = wb.create_sheet(title=name)
        style_month_sheet(ws, year, month, prefill)
        # keep tabs in chronological order
        from ..model import parse_tab_name

        wb._sheets.sort(key=lambda s: parse_tab_name(s.title) or (9999, 12))
        self._save(wb)
        return name
