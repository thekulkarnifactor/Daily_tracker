import datetime as dt

import openpyxl
import pytest

from dailytracker.model import DayEntry, EntryTemplate
from dailytracker.storage.style import MonthStyle

# --------------------------------------------------------------------- storage


def test_template_crud(storage):
    storage.save_template(EntryTemplate("Leave", project="Leave", task="Leave"))
    storage.save_template(EntryTemplate("BnB dev", project="BnB", task="Core Dev - Coding", status="Done"))
    assert [t.name for t in storage.list_templates()] == ["BnB dev", "Leave"]

    storage.save_template(EntryTemplate("bnb DEV", project="BnB2"))  # same name, case-insensitive
    assert storage.get_template("BnB dev").project == "BnB2"
    assert len(storage.list_templates()) == 2

    storage.save_template(EntryTemplate("BnB build", project="BnB"), original_name="bnb dev")  # rename
    assert [t.name for t in storage.list_templates()] == ["BnB build", "Leave"]

    assert storage.delete_template("leave")
    assert not storage.delete_template("missing")
    assert [t.name for t in storage.list_templates()] == ["BnB build"]


def test_templates_tab_is_not_a_month(storage):
    storage.save_template(EntryTemplate("X", project="p"))
    storage.save_entry(DayEntry(dt.date(2026, 11, 17), project="real"))
    assert storage.find_tab(2026, 11) == "Nov-26"
    assert storage.list_tabs()[-1] == "Templates"


def test_apply_template_skips_weekends_and_logged_days(storage):
    storage.save_entry(DayEntry(dt.date(2026, 11, 17), project="Keep"))
    t = EntryTemplate("Std", project="BnB", status="Done")
    days = [dt.date(2026, 11, d) for d in range(16, 23)]  # Mon..Sun
    written, skipped = storage.apply_template(t, days)
    assert (written, skipped) == (4, 1)
    assert storage.get_entry(dt.date(2026, 11, 17)).project == "Keep"
    assert storage.get_entry(dt.date(2026, 11, 18)).project == "BnB"
    assert storage.get_entry(dt.date(2026, 11, 21)).state == "weekend"

    written, _ = storage.apply_template(t, days, overwrite=True)
    assert written == 5 and storage.get_entry(dt.date(2026, 11, 17)).project == "BnB"


def test_apply_template_across_months_creates_tabs(storage):
    t = EntryTemplate("Std", project="BnB")
    days = [dt.date(2026, 12, 30) + dt.timedelta(days=i) for i in range(5)]  # Wed 30 Dec .. Sun 3 Jan
    written, _ = storage.apply_template(t, days)
    assert written == 3
    assert {"Dec-26", "Jan-27"} <= set(storage.list_tabs())


def test_month_style_used_for_new_tabs(storage, excel_path):
    look = MonthStyle(
        headers=["Day", "Client", "Type", "Notes", "Owner", "State"],
        header_bg="#000000",
        weekend_label="Off",
        spacer_rows=False,
        merge_weekends=False,
        column_widths=[10, 20, 30, 40, 10, 10],
    )
    storage.save_month_style(look)
    assert storage.month_style().header_bg == "000000"
    storage.create_month(2027, 2)

    wb = openpyxl.load_workbook(excel_path)
    ws = wb["Feb-27"]
    assert [c.value for c in ws[1]] == look.headers
    assert ws.cell(row=1, column=1).fill.start_color.rgb.endswith("000000")
    assert ws.cell(row=7, column=1).value.date() == dt.date(2027, 2, 6)  # no spacer rows
    assert ws.cell(row=7, column=3).value == "Off"
    assert not ws.merged_cells.ranges
    assert ws.column_dimensions["D"].width == 40
    assert wb["_config"].sheet_state == "hidden"
    # reading still works with renamed headers
    storage.save_entry(DayEntry(dt.date(2027, 2, 8), project="P"))
    assert storage.get_entry(dt.date(2027, 2, 8)).project == "P"

    storage.save_month_style(None)
    assert storage.month_style() == MonthStyle()


def test_month_style_validation():
    with pytest.raises(ValueError):
        MonthStyle(header_bg="red").validate()
    with pytest.raises(ValueError):
        MonthStyle(headers=["a", "", "c", "d", "e", "f"]).validate()
    assert MonthStyle(column_widths=[1, 500, 10, 10, 10, 10]).validate().column_widths[:2] == [4, 120]
    assert MonthStyle.from_json("not json") == MonthStyle()
    assert MonthStyle.from_json('{"header_bg": "abcdef", "unknown": 1}').header_bg == "ABCDEF"


# ---------------------------------------------------------------------- routes


def test_templates_pages_and_flow(client, storage):
    assert client.get("/templates").status_code == 200
    client.post(
        "/templates/save",
        data={
            "name": "Std",
            "project": "BnB",
            "category": "Core Dev - Coding",
            "details": "1. standup",
            "status": "Done",
        },
    )
    assert storage.get_template("Std").details == "1. standup"

    page = client.get("/?month=2026-11").data
    assert b'id="templates-data"' in page and b"Std" in page

    resp = client.post("/templates/apply", data={"name": "Std", "start": "2026-11-16", "end": "2026-11-22"})
    assert resp.status_code == 302 and "month=2026-11" in resp.headers["Location"]
    assert storage.get_entry(dt.date(2026, 11, 20)).project == "BnB"

    assert client.get("/templates?edit=Std").status_code == 200
    client.post("/templates/delete", data={"name": "Std"})
    assert storage.list_templates() == []


def test_apply_rejects_huge_range_and_missing_template(client, storage):
    storage.save_template(EntryTemplate("Std", project="x"))
    client.post("/templates/apply", data={"name": "Std", "start": "2026-01-01", "end": "2026-12-31"})
    client.post("/templates/apply", data={"name": "Nope", "start": "2026-11-16", "end": "2026-11-17"})
    assert not storage.get_entry(dt.date(2026, 11, 16)).has_content


def test_save_template_next_is_safe(client):
    resp = client.post("/templates/save", data={"name": "A", "next": "//evil.com"})
    assert resp.headers["Location"].endswith("/templates")


def test_month_template_page_save_reset_create(client, storage):
    assert client.get("/month-template").status_code == 200
    form = {f"header_{i}": h for i, h in enumerate(["D", "P", "T", "N", "A", "S"])}
    form |= {f"width_{i}": "12" for i in range(6)}
    form |= {f"bg_{i}": "#101010" for i in range(7)} | {f"fg_{i}": "#ffffff" for i in range(7)}
    form |= {
        "header_bg": "#222222",
        "header_fg": "#eeeeee",
        "border": "#cccccc",
        "font": "Arial",
        "font_size": "10",
        "weekend_label": "Off",
        "spacer_rows": "on",
    }
    client.post("/month-template", data=form)
    look = storage.month_style()
    assert look.headers[0] == "D" and look.font == "Arial" and look.spacer_rows and not look.merge_weekends

    client.post("/month-template", data=form | {"header_bg": "nope"})  # rejected, unchanged
    assert storage.month_style().header_bg == "222222"

    client.post("/month-template/create", data={"month": "2027-03"})
    assert "Mar-27" in storage.list_tabs()

    client.post("/month-template/reset")
    assert storage.month_style() == MonthStyle()
