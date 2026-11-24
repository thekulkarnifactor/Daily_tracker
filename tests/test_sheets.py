"""SheetsStorage against an in-memory fake of the gspread objects it uses."""

import datetime as dt
import re

import gspread
import pytest

from dailytracker.model import DayEntry, date_to_serial
from dailytracker.storage.sheets import SheetsStorage


def _a1(ref):
    m = re.fullmatch(r"([A-Z])(\d+)", ref)
    return int(m.group(2)), ord(m.group(1)) - 64


class FakeWorksheet:
    def __init__(self, title, rows, sid):
        self.title, self.row_count, self.id, self.col_count = title, rows, sid, 6
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

    def _shift(self, from_row, by):
        """Move every cell at/after from_row by `by` rows (insert >0, delete <0)."""
        moved = {}
        for (r, c), v in self.cells.items():
            if by < 0 and from_row + by <= r < from_row:
                continue  # deleted rows
            moved[(r + by, c) if r >= from_row else (r, c)] = v
        self.cells = moved
        self.row_count += by

    def get_all_values(self):
        if not self.cells:
            return []
        last_r = max(r for r, _ in self.cells)
        last_c = max(c for _, c in self.cells)
        return [[str(self.cells.get((r, c), "")) for c in range(1, last_c + 1)] for r in range(1, last_r + 1)]

    def clear(self):
        self.cells.clear()

    def resize(self, rows=None, cols=None):
        self.row_count, self.col_count = rows or self.row_count, cols or self.col_count

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
        for s in self.sheets:
            if s.title == title:
                return s
        raise gspread.exceptions.WorksheetNotFound(title)

    def add_worksheet(self, title, rows, cols, index=None):
        ws = FakeWorksheet(title, rows, len(self.sheets) + 100)
        self.sheets.insert(len(self.sheets) if index is None else index, ws)
        return ws

    def batch_update(self, body):
        self.requests.extend(body["requests"])
        for r in body["requests"]:
            if "insertDimension" in r:
                rng = r["insertDimension"]["range"]
                self._sheet(rng["sheetId"])._shift(rng["startIndex"] + 1, rng["endIndex"] - rng["startIndex"])
            elif "deleteDimension" in r:
                rng = r["deleteDimension"]["range"]
                self._sheet(rng["sheetId"])._shift(
                    rng["endIndex"] + 1, -(rng["endIndex"] - rng["startIndex"])
                )

    def _sheet(self, sid):
        return next(s for s in self.sheets if s.id == sid)


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


def test_permission_error_explained(sheets):
    class Denied(FakeSpreadsheet):
        def worksheets(self):
            raise PermissionError

    sheets._spreadsheet = Denied()
    from dailytracker.storage import StorageError

    with pytest.raises(StorageError, match="Share the Daily sheet with sa@test"):
        sheets.list_tabs()


def test_templates_and_month_style_roundtrip(sheets):
    from dailytracker.model import EntryTemplate
    from dailytracker.storage.style import MonthStyle

    sheets.save_template(EntryTemplate("Standup", project="BnB", status="Done"))
    assert [t.name for t in sheets.list_templates()] == ["Standup"]
    assert sheets.spreadsheet.worksheet("Templates").cells[(1, 1)] == "Name"

    look = MonthStyle(header_bg="#112233", spacer_rows=False, merge_weekends=False)
    sheets.save_month_style(look)
    hide = [
        r for r in sheets.spreadsheet.requests if r.get("updateSheetProperties", {}).get("fields") == "hidden"
    ]
    assert hide, "_config tab should be hidden"
    sheets.refresh()
    assert sheets.month_style().header_bg == "112233"

    sheets.save_entry(DayEntry(dt.date(2026, 12, 1), project="x"))
    titles = [s.title for s in sheets.spreadsheet.sheets]
    assert titles.index("Dec-26") < titles.index("Templates")  # months stay before meta tabs
    ws = sheets.spreadsheet.worksheet("Dec-26")
    # no spacer rows: day N is on row N+1
    assert ws.cells[(32, 1)] == date_to_serial(dt.date(2026, 12, 31))
    assert not any("mergeCells" in r for r in sheets.spreadsheet.requests)


def test_multiple_projects_per_day_insert_and_delete_rows(sheets):
    d = dt.date(2026, 11, 17)
    sheets.save_entry(DayEntry(d, project="Next day guard"))  # creates the tab
    nxt = dt.date(2026, 11, 18)
    sheets.save_entry(DayEntry(nxt, project="Wed"))
    sheets.save_day(
        d, [DayEntry(d, project="BnB"), DayEntry(d, project="Workday"), DayEntry(d, project="EZ")]
    )
    day = sheets.get_day(d)
    assert [i.project for i in day.items] == ["BnB", "Workday", "EZ"]
    rows = [i.row for i in day.items]
    assert rows == [rows[0], rows[0] + 1, rows[0] + 2]
    assert sheets.get_entry(nxt).project == "Wed"  # following day shifted, not overwritten
    inserts = [r for r in sheets.spreadsheet.requests if "insertDimension" in r]
    assert inserts and inserts[-1]["insertDimension"]["inheritFromBefore"] is True

    sheets.save_day(d, [DayEntry(d, project="Only one")])
    assert [i.project for i in sheets.get_day(d).items] == ["Only one"]
    assert sheets.get_entry(nxt).project == "Wed"
