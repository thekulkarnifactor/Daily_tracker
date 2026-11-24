import datetime as dt

import openpyxl

from dailytracker.model import DayEntry
from dailytracker.storage.sheets import SheetsStorage


def test_get_month_without_tab_returns_empty_days(storage):
    entries = storage.get_month(2026, 11)
    assert len(entries) == 30
    assert all(e.row is None and not e.has_content for e in entries)


def test_save_creates_styled_tab_and_updates(storage, excel_path, weekday):
    storage.save_entry(DayEntry(weekday, project="EZ Jobs", task="Core Dev - Coding", status="Done"))
    assert "Nov-26" in storage.list_tabs()

    entry = storage.get_entry(weekday)
    assert (entry.project, entry.status) == ("EZ Jobs", "Done")

    storage.save_entry(DayEntry(weekday, project="EZ Jobs", details="1. fixed", status="In Progress"))
    entry = storage.get_entry(weekday)
    assert entry.details == "1. fixed" and entry.status == "In Progress"

    wb = openpyxl.load_workbook(excel_path)
    ws = wb["Nov-26"]
    assert [c.value for c in ws[1]] == ["Date", "Project", "Task", "Task Details", "AssigneBy", "Status"]
    assert ws.cell(row=entry.row, column=1).fill.start_color.rgb.endswith("305496")  # Tuesday colour
    assert ws.merged_cells.ranges  # weekend blocks merged


def test_clear_entry(storage, weekday):
    storage.save_entry(DayEntry(weekday, project="X", status="Done"))
    storage.clear_entry(weekday)
    assert not storage.get_entry(weekday).has_content


def test_formula_like_text_is_stored_literally(storage, weekday):
    storage.save_entry(DayEntry(weekday, project="=1+1", details="+91 9999"))
    assert storage.get_entry(weekday).project == "=1+1"


def test_fill_month_only_fills_empty_days(storage, weekday):
    storage.save_entry(DayEntry(weekday, project="Keep me"))
    other = weekday + dt.timedelta(days=1)
    written = storage.fill_month(
        2026, 11, {weekday: ["Overwrite", "", "", "", ""], other: ["Imported", "", "", "", ""]}
    )
    assert written == 1
    assert storage.get_entry(weekday).project == "Keep me"
    assert storage.get_entry(other).project == "Imported"


def test_fill_month_creates_tab_with_prefill(storage):
    d = dt.date(2024, 1, 9)
    storage.fill_month(2024, 1, {d: ["Ellicium", "Core Dev - Coding", "x", "", "Done"]})
    assert storage.get_entry(d).project == "Ellicium"


def test_tabs_kept_in_order(storage):
    storage.save_entry(DayEntry(dt.date(2026, 12, 1), project="b"))
    storage.save_entry(DayEntry(dt.date(2026, 10, 1), project="a"))
    assert storage.list_tabs() == ["Oct-26", "Dec-26"]


def test_reads_legacy_tab_names_and_string_dates(storage, excel_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sept-23"
    ws.append(["Date", "Project", "Task", "Task Details", "AssigneBy", "Status"])
    ws.append(["09/05/2023", "Legacy", "Core Dev - Coding", "", "", "Done"])
    wb.save(excel_path)
    entry = storage.get_entry(dt.date(2023, 9, 5))
    assert entry.project == "Legacy"


def test_sheets_format_requests_shape():
    from dailytracker.model import month_layout

    layout = month_layout(2026, 11)
    reqs = SheetsStorage._format_requests(123, layout)
    merges = [r for r in reqs if "mergeCells" in r]
    # Nov 2026 has full weekends on 7-8, 14-15, 21-22, 28-29 (the 1st is a lone Sunday)
    assert len(merges) == 4
    assert all(r["mergeCells"]["range"]["sheetId"] == 123 for r in merges)


def test_blank_date_row_inferred_from_previous_day(storage, excel_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jan-24"
    ws.append(["Date", "Project", "Task", "Task Details", "AssigneBy", "Status"])
    ws.append([dt.datetime(2024, 1, 2), "SXR", "Core Dev - Coding", "a", "", "Done"])
    ws.append(["   ", "SXR", "Core Dev - Coding", "b", "", "Done"])
    ws.append([dt.datetime(2024, 1, 4), "SXR", "Core Dev - Coding", "c", "", "Done"])
    wb.save(excel_path)
    assert storage.get_entry(dt.date(2024, 1, 3)).details == "b"
    assert storage.get_entry(dt.date(2024, 1, 4)).details == "c"


def test_multiple_projects_per_day(storage, excel_path):
    d = dt.date(2026, 11, 20)  # Friday, the weekend merge (21-22) sits just below
    storage.save_entry(DayEntry(dt.date(2026, 11, 23), project="Monday"))
    storage.save_day(
        d,
        [
            DayEntry(d, project="BnB", task="Core Dev - Coding", status="Done"),
            DayEntry(d, project="Workday", status="In Progress"),
        ],
    )
    day = storage.get_day(d)
    assert [i.project for i in day.items] == ["BnB", "Workday"]
    assert day.state == "progress" and day.projects == ["BnB", "Workday"]
    assert storage.get_entry(dt.date(2026, 11, 23)).project == "Monday"

    wb = openpyxl.load_workbook(excel_path)
    ws = wb["Nov-26"]
    extra = day.items[1].row
    assert ws.cell(row=extra, column=1).value.date() == d
    assert ws.cell(row=extra, column=1).fill.start_color.rgb.endswith("D9E1F2")  # Friday colour copied
    sat = next(i.row for i in storage.get_day(dt.date(2026, 11, 21)).items)
    assert any(
        r.min_row == sat and r.max_row == sat + 1 for r in ws.merged_cells.ranges
    )  # weekend merge moved

    storage.save_day(d, [DayEntry(d, project="Just one", status="Done")])
    assert [i.project for i in storage.get_day(d).items] == ["Just one"]
    storage.clear_entry(d)
    assert not storage.get_day(d).has_content and len(storage.get_day(d).items) == 1
    assert storage.get_entry(dt.date(2026, 11, 23)).project == "Monday"


def test_fill_month_with_multi_project_days(storage):
    d = dt.date(2026, 12, 2)
    storage.fill_month(2026, 12, {d: [["A", "", "", "", "Done"], ["B", "", "", "", "Done"]]})
    assert storage.get_day(d).projects == ["A", "B"]
    storage.fill_month(2026, 12, {d: [["C", "", "", "", ""]]}, overwrite=True)
    assert storage.get_day(d).projects == ["C"]
