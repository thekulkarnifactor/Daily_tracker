"""Import existing Excel workbooks into the configured storage (your Google Sheet).

Typical one-time migration::

    python -m scripts.import_excel --daily Daily.xlsx --history "Daily Ellicium.xlsx"

* Months missing from the Google Sheet are created as styled tabs.
* For months that already exist, only **empty** days are filled, so nothing
  you have typed in the sheet is overwritten (use ``--overwrite`` to force).
* ``--daily`` wins over ``--history`` when both have an entry for a day.
* ``--dry-run`` prints what would change without writing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailytracker.config import Settings  # noqa: E402
from dailytracker.importer import read_workbook  # noqa: E402
from dailytracker.storage import build_storage  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--daily", help="Current workbook, e.g. Daily.xlsx")
    parser.add_argument("--history", help="Historical workbook, e.g. 'Daily Ellicium.xlsx'")
    parser.add_argument("--overwrite", action="store_true", help="Replace days that already have content")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not (args.daily or args.history):
        parser.error("pass --daily and/or --history")

    merged: dict[tuple[int, int], dict[dt.date, list[str]]] = defaultdict(dict)
    for path in filter(None, [args.history, args.daily]):  # daily last so it wins
        print(f"Reading {path}")
        months, skipped = read_workbook(path)
        for name in skipped:
            print(f"  skip tab {name!r} (not a month)")
        for ym, days in months.items():
            merged[ym].update(days)

    settings = Settings()
    target = build_storage(settings)
    print(f"Target: {target.name} ({settings.google_sheet_id or settings.excel_path})")

    total = 0
    for ym in sorted(merged):
        days = merged[ym]
        tab = target.find_tab(*ym)
        if args.dry_run:
            if tab:
                existing = {e.date for e in target.get_month(*ym) if e.has_content}
                todo = len(days) if args.overwrite else len(set(days) - existing)
            else:
                todo = len(days)
            print(f"  {ym[0]}-{ym[1]:02d}: {'update ' + tab if tab else 'create tab'} · {todo} day(s)")
            total += todo
            continue
        written = target.fill_month(*ym, days, overwrite=args.overwrite)
        print(f"  {ym[0]}-{ym[1]:02d}: {'updated ' + tab if tab else 'created tab'} · {written} day(s)")
        total += written

    print(f"Done. {total} day(s) {'would be ' if args.dry_run else ''}written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
