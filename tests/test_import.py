import datetime as dt
import io

import pytest

from dailytracker.importer import analyze, load_staged, read_workbook, run_import, stage_upload
from dailytracker.model import DayEntry
from dailytracker.storage.excel import ExcelStorage

D = dt.date


@pytest.fixture
def source_file(tmp_path):
    """A small 'old Daily.xlsx': Oct-26 with 3 days, Sept-23 legacy tab, a Template tab."""
    path = str(tmp_path / "old.xlsx")
    src = ExcelStorage(path, cache_ttl=0)
    src.save_entry(DayEntry(D(2026, 10, 1), project="BnB", task="Core Dev - Coding", status="Done"))
    src.save_entry(DayEntry(D(2026, 10, 2), project="BnB", details="mapping", status="Done"))
    src.save_entry(DayEntry(D(2026, 10, 5), project="EZ Jobs", status="Done"))
    src.save_entry(DayEntry(D(2023, 9, 4), project="SXR", status="Done"))
    import openpyxl

    wb = openpyxl.load_workbook(path)
    wb["Sep-23"].title = "Sept-23"
    wb.create_sheet("Template")
    wb.save(path)
    return path


def test_read_workbook(source_file):
    months, skipped = read_workbook(source_file)
    assert set(months) == {(2026, 10), (2023, 9)}
    assert len(months[(2026, 10)]) == 3
    assert skipped == ["Template"]


def test_analyze_and_run(source_file, storage):
    storage.save_entry(
        DayEntry(D(2026, 10, 1), project="BnB", task="Core Dev - Coding", status="Done")
    )  # same
    storage.save_entry(DayEntry(D(2026, 10, 2), project="Other"))  # conflict
    months, _ = read_workbook(source_file)

    plans = {p.key: p for p in analyze(months, storage)}
    oct_ = plans["2026-10"]
    assert (oct_.same, len(oct_.conflicts), oct_.new) == (1, 1, ["2026-10-05"])
    assert plans["2023-09"].tab is None  # will be created

    written, touched = run_import(months, storage, {(2026, 10), (2023, 9)})
    assert (written, touched) == (2, 2)
    assert storage.get_entry(D(2026, 10, 2)).project == "Other"  # kept
    assert storage.get_entry(D(2026, 10, 5)).project == "EZ Jobs"
    assert storage.get_entry(D(2023, 9, 4)).project == "SXR"

    written, _ = run_import(months, storage, {(2026, 10)}, overwrite=True)
    assert written == 1 and storage.get_entry(D(2026, 10, 2)).project == "BnB"
    assert run_import(months, storage, {(2026, 10)}, overwrite=True) == (0, 0)  # idempotent


def test_only_selected_months_are_imported(source_file, storage):
    months, _ = read_workbook(source_file)
    run_import(months, storage, {(2023, 9)})
    assert storage.find_tab(2026, 10) is None


def test_stage_roundtrip_and_bad_tokens(source_file):
    months, _ = read_workbook(source_file)
    token = stage_upload(months, "old.xlsx")
    loaded, name = load_staged(token)
    assert loaded == months and name == "old.xlsx"
    assert load_staged("../../etc/passwd") is None
    assert load_staged("nope") is None


# ---------------------------------------------------------------- routes


def _upload(client, path, name="Daily.xlsx"):
    with open(path, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), name)}
    return client.post("/import/preview", data=data, content_type="multipart/form-data")


def test_import_flow(client, storage, source_file):
    assert client.get("/import").status_code == 200
    resp = _upload(client, source_file)
    assert resp.status_code == 302 and "/import/review/" in resp.headers["Location"]
    token = resp.headers["Location"].rsplit("/", 1)[-1]

    page = client.get(f"/import/review/{token}")
    assert page.status_code == 200 and b"Oct 2026" in page.data and b"Will create tab" in page.data

    resp = client.post("/import/run", data={"token": token, "months": ["2026-10"], "mode": "empty"})
    assert resp.status_code == 302 and "month=2026-10" in resp.headers["Location"]
    assert storage.get_entry(D(2026, 10, 5)).project == "EZ Jobs"
    assert storage.find_tab(2023, 9) is None
    assert client.get(f"/import/review/{token}").status_code == 302  # token used up


def test_import_rejects_bad_files(client, tmp_path):
    bad = tmp_path / "x.xlsx"
    bad.write_bytes(b"not a zip")
    resp = _upload(client, bad)
    assert resp.headers["Location"].endswith("/import")
    resp = client.post(
        "/import/preview", data={"file": (io.BytesIO(b"a,b"), "x.csv")}, content_type="multipart/form-data"
    )
    assert resp.headers["Location"].endswith("/import")


def test_import_requires_month_selection(client, source_file):
    token = _upload(client, source_file).headers["Location"].rsplit("/", 1)[-1]
    resp = client.post("/import/run", data={"token": token})
    assert f"/import/review/{token}" in resp.headers["Location"]
