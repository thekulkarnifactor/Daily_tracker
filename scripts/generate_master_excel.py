"""Generate a blank, styled Daily.xlsx for a range of months (offline use).

python -m scripts.generate_master_excel --start 2026-05 --end 2027-05 --out Daily.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailytracker.model import shift_month, tab_name  # noqa: E402
from dailytracker.storage.excel import style_month_sheet  # noqa: E402


def _ym(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-05", type=_ym)
    parser.add_argument("--end", default="2027-05", type=_ym)
    parser.add_argument("--out", default="Daily.xlsx")
    args = parser.parse_args(argv)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cur = args.start
    while cur <= args.end:
        style_month_sheet(wb.create_sheet(tab_name(*cur)), *cur)
        cur = shift_month(*cur, 1)
    wb.save(args.out)
    print(f"Wrote {args.out} with {len(wb.sheetnames)} month tabs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
