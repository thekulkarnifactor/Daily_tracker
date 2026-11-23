import datetime as dt

import pytest

from dailytracker.model import (
    DayEntry,
    date_to_serial,
    match_tab,
    month_layout,
    parse_date,
    parse_tab_name,
    serial_to_date,
    shift_month,
    summarize,
    tab_name,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Nov-26", (2026, 11)),
        ("Sept-23", (2023, 9)),
        ("June-25", (2025, 6)),
        ("March-26", (2026, 3)),
        ("July-23", (2023, 7)),
        ("Dec 2024", (2024, 12)),
        ("Template", None),
        ("Ma-26", None),
    ],
)
def test_parse_tab_name(name, expected):
    assert parse_tab_name(name) == expected


def test_match_tab_prefers_canonical():
    assert match_tab(["Sept-23", "Sep-23"], 2023, 9) == "Sep-23"
    assert match_tab(["Sept-23"], 2023, 9) == "Sept-23"
    assert match_tab(["Oct-23"], 2023, 9) is None
    assert tab_name(2026, 11) == "Nov-26"


def test_parse_date_variants():
    assert parse_date(dt.datetime(2026, 11, 3, 0, 0)) == dt.date(2026, 11, 3)
    assert parse_date(date_to_serial(dt.date(2026, 11, 3))) == dt.date(2026, 11, 3)
    assert parse_date("2026-11-03") == dt.date(2026, 11, 3)
    # ambiguous string resolved by the tab's month
    assert parse_date("03/11/2026", 2026, 11) == dt.date(2026, 11, 3)
    assert parse_date("11/03/2026", 2026, 11) == dt.date(2026, 11, 3)
    assert parse_date("") is None
    assert parse_date("Weekend") is None
    assert parse_date(5) is None


def test_serial_roundtrip():
    d = dt.date(2027, 2, 28)
    assert serial_to_date(date_to_serial(d)) == d


def test_month_layout_spacers():
    rows = month_layout(2026, 11)  # Nov 2026 starts on a Sunday
    dates = [r for r in rows if r]
    assert len(dates) == 30
    assert rows[0] == dt.date(2026, 11, 1)
    assert rows[1] is None  # spacer after Sunday
    # spacer before each Saturday except at the top
    for i, r in enumerate(rows):
        if r and r.weekday() == 5 and i > 0:
            assert rows[i - 1] is None


def test_shift_month():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)


def test_entry_states():
    tue = dt.date(2026, 11, 17)
    assert DayEntry(tue).state == "empty"
    assert DayEntry(tue, project="X", status="Done").state == "done"
    assert DayEntry(tue, project="X", status="In Progress").state == "progress"
    assert DayEntry(tue, project="Leave").state == "leave"
    assert DayEntry(tue, project="X", task="Core Dev - Coding").state == "logged"
    sat = dt.date(2026, 11, 21)
    assert DayEntry(sat, project="Saturday", task="Weekend").state == "weekend"
    assert DayEntry(tue, project="None").project == ""


def test_summarize():
    days = [DayEntry(dt.date(2026, 11, d)) for d in range(16, 23)]  # Mon..Sun
    days[0].project, days[0].status = "A", "Done"
    days[1].project = "Leave"
    s = summarize(days, today=dt.date(2026, 11, 18))
    assert (s.workdays, s.logged, s.done, s.leave, s.pending) == (3, 1, 1, 1, 1)


def test_weekend_with_project_label_only_is_weekend():
    sat = dt.date(2024, 1, 6)
    assert DayEntry(sat, project="SXR", task="Weekend").state == "weekend"
    assert DayEntry(sat, project="SXR", details="prod fix").state == "logged"


def test_service_account_parsing(monkeypatch):
    import base64
    import json

    from dailytracker.config import load_service_account_info

    key = {"type": "service_account", "private_key": "x", "client_email": "a@b"}
    for value in (
        json.dumps(key),
        "'" + json.dumps(key) + "'",
        base64.b64encode(json.dumps(key).encode()).decode(),
        "﻿" + json.dumps(key),
    ):
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", value)
        assert load_service_account_info()["client_email"] == "a@b"
    for bad in ("113309794645971820696", "service-account.json", '{"type": "x"}', "{not json"):
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", bad)
        with pytest.raises(RuntimeError, match="ENTIRE"):
            load_service_account_info()
