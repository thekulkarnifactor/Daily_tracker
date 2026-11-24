from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import current_user, login_required
from .model import HEADERS, STATUSES, TASK_CATEGORIES, DayEntry, parse_tab_name, shift_month, summarize
from .storage import Storage, StorageError

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

MAX_LEN = {"project": 120, "category": 120, "details": 5000, "assignee": 120, "status": 40}


def storage() -> Storage:
    return current_app.config["STORAGE"]


def today() -> dt.date:
    return dt.datetime.now(ZoneInfo(current_app.config["SETTINGS"].timezone)).date()


def _parse_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m")
        return parsed.year, parsed.month
    except ValueError:
        return parse_tab_name(value)


def _month_param(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _timeline() -> list[tuple[int, int]]:
    settings = current_app.config["SETTINGS"]
    start = _parse_month(settings.timeline_start) or (2023, 7)
    t = today()
    end = shift_month(t.year, t.month, settings.timeline_months_ahead)
    return storage().available_months(start, end)


@bp.get("/")
@login_required
def dashboard():
    t = today()
    prefill = _quick_add_prefill()
    ym = _parse_month(request.args.get("month") or request.args.get("sheet")) or (t.year, t.month)
    if prefill:
        ym = (prefill["day"].year, prefill["day"].month)
    year, month = ym
    entries = storage().get_month(year, month)
    tab = storage().find_tab(year, month)

    known_tasks = sorted({e.task for e in entries if e.task and e.task not in TASK_CATEGORIES})
    prev_ym, next_ym = shift_month(year, month, -1), shift_month(year, month, 1)

    return render_template(
        "index.html",
        user=current_user(),
        entries=entries,
        pad_days=dt.date(year, month, 1).weekday(),
        month_label=dt.date(year, month, 1).strftime("%B %Y"),
        month_param=_month_param(year, month),
        prev_month=_month_param(*prev_ym),
        next_month=_month_param(*next_ym),
        timeline=[(_month_param(y, m), dt.date(y, m, 1).strftime("%b %Y")) for y, m in reversed(_timeline())],
        tab=tab,
        summary=summarize(entries, t),
        categories=TASK_CATEGORIES + known_tasks,
        statuses=STATUSES,
        today=t,
        backend=storage().name,
        templates=[t.to_dict() for t in storage().list_templates()],
        prefill={**prefill, "day": prefill["day"].isoformat()} if prefill else None,
    )


def _quick_add_prefill() -> dict | None:
    """Quick-add link: ``/?day=2026-11-24&project=…&category=…&details=…&assignee=…&status=…``

    Opens that day's dialog with the fields filled in. Nothing is saved until
    the user presses Save, so the link is safe to share or bookmark.
    """
    raw = request.args.get("day")
    if not raw:
        return None
    try:
        day = dt.date.fromisoformat(raw)
    except ValueError:
        return None
    if day.weekday() >= 5:
        return None
    fields = {k: (request.args.get(k) or "").strip()[:limit] for k, limit in MAX_LEN.items()}
    return {"day": day, **{k: v for k, v in fields.items() if v}}


def _form_date() -> dt.date:
    try:
        return dt.date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        abort(400, "Invalid date")


def _back(d: dt.date):
    return redirect(url_for("main.dashboard", month=_month_param(d.year, d.month)) + f"#d{d.isoformat()}")


@bp.post("/entry")
@login_required
def save_entry():
    d = _form_date()
    if d.weekday() >= 5:
        abort(400, "Weekend days are not editable")
    fields = {k: (request.form.get(k) or "").strip()[:limit] for k, limit in MAX_LEN.items()}
    if not fields["project"]:
        flash("Project is required.", "error")
        return _back(d)
    entry = DayEntry(
        date=d,
        project=fields["project"],
        task=fields["category"],
        details=fields["details"],
        assignee=fields["assignee"],
        status=fields["status"],
    )
    storage().save_entry(entry)
    flash(f"Saved {d.strftime('%a %d %b')}.", "success")
    return _back(d)


@bp.post("/entry/clear")
@login_required
def clear_entry():
    d = _form_date()
    if d.weekday() >= 5:
        abort(400, "Weekend days are not editable")
    storage().clear_entry(d)
    flash(f"Cleared {d.strftime('%a %d %b')}.", "success")
    return _back(d)


@bp.post("/sync")
@login_required
def sync():
    storage().refresh()
    flash("Reloaded from the sheet.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.get("/api/month/<month>")
@login_required
def api_month(month: str):
    ym = _parse_month(month) or abort(404)
    entries = storage().get_month(*ym)
    s = summarize(entries, today())
    return jsonify(
        month=_month_param(*ym),
        summary={**s.__dict__, "pending": s.pending},
        entries=[{**e.to_dict(), "state": e.state} for e in entries],
    )


@bp.get("/export/<month>.csv")
@login_required
def export_csv(month: str):
    ym = _parse_month(month) or abort(404)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for e in storage().get_month(*ym):
        writer.writerow([e.date.isoformat(), *e.values()])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=daily-{_month_param(*ym)}.csv"},
    )


@bp.get("/entry")
@bp.get("/entry/clear")
@bp.get("/sync")
def post_only_redirect():
    """Typing/refreshing a form URL (e.g. after an error page) just goes back to the calendar."""
    return redirect(url_for("main.dashboard"))


@bp.get("/healthz")
def healthz():
    return {"status": "ok"}


@bp.get("/readyz")
def readyz():
    try:
        storage().ping()
    except StorageError as exc:
        log.error("readiness check failed: %s", exc)
        return {"status": "unavailable"}, 503
    return {"status": "ready", "backend": storage().name}
