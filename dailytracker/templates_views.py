"""Entry templates, bulk apply, and the month-sheet template editor."""

from __future__ import annotations

import calendar
import datetime as dt

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import current_user, login_required
from .model import STATUSES, TASK_CATEGORIES, EntryTemplate
from .storage.style import WEEKDAY_NAMES, MonthStyle
from .views import _month_param, _parse_month, storage, today

bp = Blueprint("tpl", __name__)

MAX_APPLY_DAYS = 120


def _safe_next(default: str) -> str:
    target = request.form.get("next") or request.args.get("next") or ""
    return target if target.startswith("/") and not target.startswith("//") else default


def _form_template() -> EntryTemplate:
    f = request.form
    return EntryTemplate(
        name=f.get("name", ""),
        project=f.get("project", ""),
        task=f.get("category", ""),
        details=f.get("details", ""),
        assignee=f.get("assignee", ""),
        status=f.get("status", ""),
    )


# ------------------------------------------------------------------ entry templates


@bp.get("/templates")
@login_required
def templates():
    t = today()
    ym = _parse_month(request.args.get("month")) or (t.year, t.month)
    first = dt.date(*ym, 1)
    last = dt.date(*ym, calendar.monthrange(*ym)[1])
    items = storage().list_templates()
    editing = storage().get_template(request.args.get("edit", "")) if request.args.get("edit") else None
    known = sorted({i.task for i in items if i.task and i.task not in TASK_CATEGORIES})
    return render_template(
        "templates.html",
        user=current_user(),
        items=items,
        editing=editing,
        categories=TASK_CATEGORIES + known,
        statuses=STATUSES,
        apply_start=first.isoformat(),
        apply_end=last.isoformat(),
        apply_template=request.args.get("use", ""),
        month_param=_month_param(*ym),
        backend=storage().name,
    )


@bp.post("/templates/save")
@login_required
def save_template():
    template = _form_template()
    if not template.name:
        flash("Give the template a name.", "error")
    else:
        storage().save_template(template, original_name=request.form.get("original_name"))
        flash(f"Template “{template.name}” saved.", "success")
    return redirect(_safe_next(url_for("tpl.templates")))


@bp.post("/templates/delete")
@login_required
def delete_template():
    name = request.form.get("name", "")
    if storage().delete_template(name):
        flash(f"Template “{name}” deleted.", "success")
    return redirect(url_for("tpl.templates"))


@bp.post("/templates/apply")
@login_required
def apply_template():
    template = storage().get_template(request.form.get("name", ""))
    try:
        start = dt.date.fromisoformat(request.form.get("start", ""))
        end = dt.date.fromisoformat(request.form.get("end", ""))
    except ValueError:
        flash("Pick a valid start and end date.", "error")
        return redirect(url_for("tpl.templates"))
    if not template:
        flash("Choose a template to apply.", "error")
        return redirect(url_for("tpl.templates"))
    if end < start:
        start, end = end, start
    span = (end - start).days + 1
    if span > MAX_APPLY_DAYS:
        flash(f"Apply to at most {MAX_APPLY_DAYS} days at a time.", "error")
        return redirect(url_for("tpl.templates"))

    dates = [start + dt.timedelta(days=i) for i in range(span)]
    overwrite = request.form.get("mode") == "overwrite"
    written, skipped = storage().apply_template(template, dates, overwrite=overwrite)
    msg = f"Applied “{template.name}” to {written} day{'s' if written != 1 else ''}"
    if skipped:
        msg += f" · {skipped} already logged, left as is"
    flash(msg + ".", "success")
    return redirect(url_for("main.dashboard", month=_month_param(start.year, start.month)))


# ----------------------------------------------------------------- month template


@bp.get("/month-template")
@login_required
def month_template():
    t = today()
    upcoming = []
    y, m = t.year, t.month
    for _ in range(6):
        y, m = (y + (m == 12), m % 12 + 1)
        upcoming.append(
            (_month_param(y, m), dt.date(y, m, 1).strftime("%b %Y"), bool(storage().find_tab(y, m)))
        )
    return render_template(
        "month_template.html",
        user=current_user(),
        look=storage().month_style(),
        defaults=MonthStyle(),
        weekday_names=WEEKDAY_NAMES,
        upcoming=upcoming,
        backend=storage().name,
    )


@bp.post("/month-template")
@login_required
def save_month_template():
    f = request.form
    try:
        look = MonthStyle(
            headers=[f.get(f"header_{i}", "") for i in range(6)],
            header_bg=f.get("header_bg", ""),
            header_fg=f.get("header_fg", ""),
            border=f.get("border", ""),
            weekdays=[[f.get(f"bg_{i}", ""), f.get(f"fg_{i}", "")] for i in range(7)],
            column_widths=[int(f.get(f"width_{i}", "0") or 0) for i in range(6)],
            font=f.get("font", "Calibri"),
            font_size=int(f.get("font_size", "11") or 11),
            weekend_label=f.get("weekend_label", ""),
            spacer_rows=f.get("spacer_rows") == "on",
            merge_weekends=f.get("merge_weekends") == "on",
        ).validate()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tpl.month_template"))
    storage().save_month_style(look)
    flash("Month template saved. New month tabs will use it.", "success")
    return redirect(url_for("tpl.month_template"))


@bp.post("/month-template/reset")
@login_required
def reset_month_template():
    storage().save_month_style(None)
    flash("Month template reset to the original design.", "success")
    return redirect(url_for("tpl.month_template"))


@bp.post("/month-template/create")
@login_required
def create_month_tab():
    ym = _parse_month(request.form.get("month"))
    if not ym:
        flash("Pick a month.", "error")
        return redirect(url_for("tpl.month_template"))
    existed = storage().find_tab(*ym)
    tab = storage().create_month(*ym)
    flash(f"Tab {tab} {'already exists' if existed else 'created from the template'}.", "success")
    return redirect(url_for("tpl.month_template"))
