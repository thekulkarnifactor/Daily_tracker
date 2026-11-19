"""SheetsStorage against an in-memory fake of the gspread objects it uses."""

import datetime as dt
import re

import pytest

from dailytracker.model import DayEntry, date_to_serial
from dailytracker.storage.sheets import SheetsStorage


def _a1(ref):
    m = re.fullmatch(r"([A-Z])(\d+)", ref)
    return int(m.group(2)), ord(m.group(1)) - 64


class FakeWorksheet:
    def __init__(self, title, rows, sid):
        self.title, self.row_count, self.id = title, rows, sid
        self.cells: dict[tuple[int, int], object] = {}
        self.formats = []

    def _put(self, start, values):
        r0, c0 = _a1(start)
        for i, row in enumerate(values):
            for j, v in enumerate(row):
                self.cells[(r0 + i, c0 + j)] = v

    def get(self, rng, **kw):
        assert kw["value_render_option"].value == "UNFORMATTED_VALUE"
        last = max((r for r, _ in self.cells), default=1)
        out = []
        for r in range(2, last + 1):
            row = [self.cells.get((r, c), "") for c in range(1, 7)]
            while row and row[-1] == "":
                row.pop()
            out.append(row)
        return out

    def batch_update(self, data, value_input_option=None):
        assert value_input_option.value == "RAW"
        for item in data:
            self._put(item["range"].split(":")[0], item["values"])

    def update(self, values, range_name, value_input_option=None):
        assert value_input_option.value == "RAW"
        self._put(range_name.split(":")[0], values)

    def add_rows(self, n):
        self.row_count += n

    def format(self, rng, fmt):
        self.formats.append((rng, fmt))


class FakeSpreadsheet:
    def __init__(self):
        self.sheets: list[FakeWorksheet] = []
        self.requests = []

    def worksheets(self):
        return list(self.sheets)

    def worksheet(self, title):
        return next(s for s in self.sheets if s.title == title)

    def add_worksheet(self, title, rows, cols, index=None):
        ws = FakeWorksheet(title, rows, len(self.sheets) + 100)
        self.sheets.insert(len(self.sheets) if index is None else index, ws)
        return ws

    def batch_update(self, body):
        self.requests.extend(body["requests"])


@pytest.fixture
def sheets():
    store = SheetsStorage.__new__(SheetsStorage)
    super(SheetsStorage, store).__init__(cache_ttl=60)
    store.sheet_id, store.service_account_email = "x", "sa@test"
    store._spreadsheet = FakeSpreadsheet()
    return store


def test_create_tab_writes_layout_and_formats(sheets):
    d = dt.date(2026, 11, 17)
    sheets.save_entry(DayEntry(d, project="EZ Jobs", status="Done"))
    ws = sheets.spreadsheet.worksheet("Nov-26")
    assert ws.cells[(1, 1)] == "Date"
    assert ws.cells[(2, 1)] == date_to_serial(dt.date(2026, 11, 1))
    assert any("mergeCells" in r for r in sheets.spreadsheet.requests)
    entry = sheets.get_entry(d)
    assert entry.project == "EZ Jobs" and entry.row and ws.cells[(entry.row, 6)] == "Done"


def test_update_existing_row_and_cache_invalidation(sheets):
    d = dt.date(2026, 11, 18)
    sheets.save_entry(DayEntry(d, project="A"))
    row = sheets.get_entry(d).row
    sheets.save_entry(DayEntry(d, project="B", details="=cmd|' /C calc'!A0"))
    e = sheets.get_entry(d)
    assert e.row == row and e.project == "B" and e.details.startswith("=cmd")


def test_tabs_inserted_chronologically(sheets):
    sheets.save_entry(DayEntry(dt.date(2026, 12, 1), project="x"))
    sheets.save_entry(DayEntry(dt.date(2026, 10, 1), project="x"))
    sheets.save_entry(DayEntry(dt.date(2026, 11, 2), project="x"))
    assert [s.title for s in sheets.spreadsheet.sheets] == ["Oct-26", "Nov-26", "Dec-26"]


def test_missing_date_row_is_appended(sheets):
    ws = sheets.spreadsheet.add_worksheet("Nov-26", 3, 6)
    ws._put("A1", [["Date", "Project", "Task", "Task Details", "AssigneBy", "Status"]])
    ws._put("A2", [[date_to_serial(dt.date(2026, 11, 2)), "Old", "", "", "", ""]])
    sheets.save_entry(DayEntry(dt.date(2026, 11, 3), project="New"))
    assert ws.cells[(3, 2)] == "New" and ws.row_count >= 3
    assert sheets.get_entry(dt.date(2026, 11, 2)).project == "Old"
