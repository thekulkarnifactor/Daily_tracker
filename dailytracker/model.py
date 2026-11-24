"""Domain model: month tabs, day entries and the workbook layout rules."""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import asdict, dataclass, field

HEADERS = ["Date", "Project", "Task", "Task Details", "AssigneBy", "Status"]

TASK_CATEGORIES = [
    "Core Dev - Coding",
    "Core Dev - Research",
    "Core Dev - QA Testing & Automation",
    "Core Dev - Integration Testing",
    "Core Dev - DevOps",
    "Core Dev - Other",
    "Product Ops - Solution Ideation",
    "Product Ops - Roadmapping",
    "Field Ops - Documentation",
    "Field Ops - Troubleshooting",
    "Field Ops - Live Support",
    "Field Ops - Support Automation",
    "Field Ops - Demos(Int. or Ext.)",
    "Field Ops - Reporting",
    "Leave",
    "Holiday",
]

STATUSES = ["In Progress", "Done"]

WEEKEND_PLACEHOLDERS = {"saturday", "sunday", "weekend"}
_LEAVE_WORDS = (
    "leave",
    "holiday",
    "jayanti",
    "chaturthi",
    "diwali",
    "dussehra",
    "christmas",
    "republic day",
    "independence day",
    "new year",
    "outing",
    "camp",
    "sick",
    "ooo",
)

# Excel / Google Sheets serial date epoch.
_EPOCH = dt.date(1899, 12, 30)


# --------------------------------------------------------------------------- dates


def tab_name(year: int, month: int) -> str:
    """Canonical tab name, e.g. ``Nov-26``."""
    return dt.date(year, month, 1).strftime("%b-%y")


def parse_tab_name(name: str) -> tuple[int, int] | None:
    """Parse tab names like ``Nov-26``, ``Sept-23``, ``June-25`` or ``March-26``."""
    m = re.fullmatch(r"\s*([A-Za-z]+)[\s\-_]*(\d{2}|\d{4})\s*", name or "")
    if not m:
        return None
    word, yr = m.group(1).lower(), m.group(2)
    if len(word) < 3:
        return None
    for month in range(1, 13):
        if calendar.month_name[month].lower().startswith(word):
            year = int(yr) if len(yr) == 4 else 2000 + int(yr)
            return year, month
    return None


def match_tab(tab_names: list[str], year: int, month: int) -> str | None:
    """Find the tab holding a given month, preferring the canonical name."""
    canonical = tab_name(year, month)
    if canonical in tab_names:
        return canonical
    for name in tab_names:
        if parse_tab_name(name) == (year, month):
            return name
    return None


def serial_to_date(value: float) -> dt.date:
    return _EPOCH + dt.timedelta(days=int(value))


def date_to_serial(value: dt.date) -> int:
    return (value - _EPOCH).days


def parse_date(value, year: int | None = None, month: int | None = None) -> dt.date | None:
    """Parse a cell value into a date.

    Handles native dates, spreadsheet serial numbers and strings. For ambiguous
    strings like ``03/11/2026`` the interpretation that falls inside the tab's
    month wins, so both MM/DD and DD/MM sheets read correctly.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        if 20000 < value < 80000:  # ~1954..2119
            return serial_to_date(value)
        return None
    text = str(value).strip().split(" ")[0].split("T")[0]
    candidates: list[dt.date] = []
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%b-%d-%Y", "%Y/%m/%d", "%d-%b-%Y"):
        try:
            candidates.append(dt.datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    if not candidates:
        return None
    if year and month:
        for cand in candidates:
            if cand.year == year and cand.month == month:
                return cand
    return candidates[0]


def month_layout(year: int, month: int, spacers: bool = True) -> list[dt.date | None]:
    """Row layout of a month tab below the header.

    One row per day. With ``spacers`` (the original workbook design) a blank row
    is added before each Saturday (except at the top) and after each Sunday.
    """
    rows: list[dt.date | None] = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        d = dt.date(year, month, day)
        if spacers and d.weekday() == 5 and rows:
            rows.append(None)
        rows.append(d)
        if spacers and d.weekday() == 6:
            rows.append(None)
    return rows


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


# --------------------------------------------------------------------------- entries


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"None", "nan"} else text


@dataclass
class DayEntry:
    date: dt.date
    project: str = ""
    task: str = ""
    details: str = ""
    assignee: str = ""
    status: str = ""
    row: int | None = None  # 1-based spreadsheet row, if known

    def __post_init__(self) -> None:
        self.project = _clean(self.project)
        self.task = _clean(self.task)
        self.details = _clean(self.details)
        self.assignee = _clean(self.assignee)
        self.status = _clean(self.status)

    @property
    def is_weekend(self) -> bool:
        return self.date.weekday() >= 5

    @property
    def has_content(self) -> bool:
        """True when the entry holds real work, not just weekend placeholders."""
        values = [self.project, self.task, self.details, self.assignee, self.status]
        return any(v and v.lower() not in WEEKEND_PLACEHOLDERS for v in values)

    @property
    def has_work(self) -> bool:
        """Content beyond a bare project/placeholder label (used for weekends)."""
        task = self.task if self.task.lower() not in WEEKEND_PLACEHOLDERS else ""
        return bool(self.details or self.status or task)

    @property
    def is_leave(self) -> bool:
        text = " ".join([self.project, self.task, self.details]).lower()
        return any(word in text for word in _LEAVE_WORDS)

    @property
    def state(self) -> str:
        if self.is_weekend and not self.has_work:
            return "weekend"
        if self.is_leave:
            return "leave"
        if self.status.lower() == "done":
            return "done"
        if self.status.lower() == "in progress":
            return "progress"
        if self.has_content:
            return "logged"
        return "empty"

    def values(self) -> list[str]:
        """Columns B..F in sheet order."""
        return [self.project, self.task, self.details, self.assignee, self.status]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


def placeholder_values(d: dt.date, weekend_label: str = "Weekend") -> list[str]:
    """Default B..F values for a fresh row."""
    if d.weekday() == 5:
        return ["Saturday", weekend_label, "", "", ""]
    if d.weekday() == 6:
        return ["Sunday", "", "", "", ""]
    return ["", "", "", "", ""]


@dataclass
class Day:
    """One calendar day: one or more work entries (one per project), stored as rows with the same date.

    ``items[0]`` is the day's main row in the sheet (it always exists in the month
    layout); extra projects are extra rows directly below it.
    """

    date: dt.date
    items: list[DayEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.items:
            self.items = [DayEntry(self.date)]

    @property
    def primary(self) -> DayEntry:
        return self.items[0]

    @property
    def row(self) -> int | None:
        return self.primary.row

    @property
    def work(self) -> list[DayEntry]:
        """Entries that hold real content (weekend placeholders excluded)."""
        return [i for i in self.items if i.has_content]

    @property
    def is_weekend(self) -> bool:
        return self.date.weekday() >= 5

    @property
    def has_content(self) -> bool:
        return bool(self.work)

    @property
    def is_leave(self) -> bool:
        work = self.work
        return bool(work) and all(i.is_leave for i in work)

    @property
    def projects(self) -> list[str]:
        seen: list[str] = []
        for i in self.work:
            if i.project and i.project not in seen:
                seen.append(i.project)
        return seen

    @property
    def state(self) -> str:
        if self.is_weekend and not any(i.has_work for i in self.items):
            return "weekend"
        work = self.work
        if not work:
            return "empty"
        if self.is_leave:
            return "leave"
        statuses = [i.status.lower() for i in work if not i.is_leave]
        if "in progress" in statuses:
            return "progress"
        if statuses and all(s == "done" for s in statuses):
            return "done"
        return "logged"

    def item_dicts(self) -> list[dict]:
        return [
            {
                "project": i.project,
                "category": i.task,
                "details": i.details,
                "assignee": i.assignee,
                "status": i.status,
            }
            for i in self.work
        ]

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "state": self.state,
            "items": [{**i.to_dict(), "state": i.state} for i in self.work],
        }


def normalize_items(values) -> list[list[str]]:
    """Accept one row (list[str]) or several (list[list[str]]); drop empty rows."""
    if not values:
        return []
    rows = values if isinstance(values[0], (list, tuple)) else [values]
    cleaned = [[str(v or "").strip() for v in (list(r) + [""] * 5)[:5]] for r in rows]
    return [r for r in cleaned if any(r)]


@dataclass
class MonthSummary:
    workdays: int
    logged: int
    done: int
    in_progress: int
    leave: int

    @property
    def pending(self) -> int:
        return max(self.workdays - self.logged - self.leave, 0)


def summarize(entries: list[Day] | list[DayEntry], today: dt.date | None = None) -> MonthSummary:
    today = today or dt.date.today()
    workdays = [e for e in entries if not e.is_weekend]
    past = [e for e in workdays if e.date <= today]
    return MonthSummary(
        workdays=len(past),
        logged=len([e for e in past if e.has_content and not e.is_leave]),
        done=len([e for e in entries if e.state == "done"]),
        in_progress=len([e for e in entries if e.state == "progress"]),
        leave=len([e for e in entries if e.state == "leave"]),
    )


@dataclass
class EntryTemplate:
    """A reusable day entry, e.g. "BnB standup" or "Leave"."""

    name: str
    project: str = ""
    task: str = ""
    details: str = ""
    assignee: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        self.name = _clean(self.name)[:60]
        self.project = _clean(self.project)[:120]
        self.task = _clean(self.task)[:120]
        self.details = _clean(self.details)[:5000]
        self.assignee = _clean(self.assignee)[:120]
        self.status = _clean(self.status)[:40]

    def values(self) -> list[str]:
        return [self.project, self.task, self.details, self.assignee, self.status]

    def to_dict(self) -> dict:
        return asdict(self)


TEMPLATE_HEADERS = ["Name", *HEADERS[1:]]
