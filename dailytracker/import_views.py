"""Import history: upload an Excel workbook, review the differences, then import."""

from __future__ import annotations

import os
import tempfile

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import current_user, login_required
from .importer import (
    ImportFileError,
    analyze,
    discard_staged,
    load_staged,
    read_workbook,
    run_import,
    stage_upload,
)
from .views import storage

bp = Blueprint("imp", __name__)

MAX_UPLOAD_MB = 10


@bp.get("/import")
@login_required
def start():
    return render_template("import.html", user=current_user(), backend=storage().name, max_mb=MAX_UPLOAD_MB)


@bp.post("/import/preview")
@login_required
def preview():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose an Excel file to import.", "error")
        return redirect(url_for("imp.start"))
    if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
        flash(
            "That file isn't an .xlsx workbook. In Excel or Google Sheets, save it as .xlsx first.", "error"
        )
        return redirect(url_for("imp.start"))

    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        upload.save(path)
        months, skipped = read_workbook(path)
    except ImportFileError as exc:
        flash(str(exc), "error")
        return redirect(url_for("imp.start"))
    except Exception:  # corrupt or unexpected workbook
        flash(
            "This workbook couldn't be read. Check it opens in Excel and has month tabs like Nov-26.", "error"
        )
        return redirect(url_for("imp.start"))
    finally:
        os.remove(path)

    if not months:
        flash(
            "No logged days found. Tabs must be named by month (e.g. Nov-26) with dates in column A.", "error"
        )
        return redirect(url_for("imp.start"))
    token = stage_upload(months, os.path.basename(upload.filename))
    if skipped:
        flash(f"Skipped tabs that aren't months: {', '.join(skipped)}.", "success")
    return redirect(url_for("imp.review", token=token))


@bp.get("/import/review/<token>")
@login_required
def review(token: str):
    staged = load_staged(token)
    if not staged:
        flash("That upload has expired. Upload the file again.", "error")
        return redirect(url_for("imp.start"))
    months, filename = staged
    plans = analyze(months, storage())
    return render_template(
        "import_review.html",
        user=current_user(),
        backend=storage().name,
        token=token,
        filename=filename,
        plans=plans,
        totals={
            "days": sum(p.total for p in plans),
            "new": sum(len(p.new) for p in plans),
            "conflicts": sum(len(p.conflicts) for p in plans),
            "same": sum(p.same for p in plans),
            "new_tabs": sum(1 for p in plans if not p.tab),
        },
    )


@bp.post("/import/run")
@login_required
def run():
    token = request.form.get("token", "")
    staged = load_staged(token)
    if not staged:
        flash("That upload has expired. Upload the file again.", "error")
        return redirect(url_for("imp.start"))
    months, filename = staged
    chosen = set()
    for key in request.form.getlist("months"):
        try:
            y, m = map(int, key.split("-"))
        except ValueError:
            abort(400)
        chosen.add((y, m))
    if not chosen:
        flash("Select at least one month to import.", "error")
        return redirect(url_for("imp.review", token=token))

    overwrite = request.form.get("mode") == "overwrite"
    written, touched = run_import(months, storage(), chosen, overwrite=overwrite)
    discard_staged(token)
    days = f"{written} day{'s' if written != 1 else ''}"
    flash(f"Imported {days} into {touched} month{'s' if touched != 1 else ''} from {filename}.", "success")
    first = min(chosen)
    return redirect(url_for("main.dashboard", month=f"{first[0]:04d}-{first[1]:02d}"))


@bp.post("/import/cancel")
@login_required
def cancel():
    discard_staged(request.form.get("token", ""))
    return redirect(url_for("imp.start"))
