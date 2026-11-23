"""Month-sheet template: the look and layout used when a new month tab is created.

The defaults reproduce the original Daily.xlsx exactly. Users can change them on
the "Month template" page; the result is stored as JSON in the hidden ``_config``
tab of the workbook so it travels with the data.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from ..model import HEADERS

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")

ROW_HEIGHT = 22
SPACER_HEIGHT = 18
HEADER_HEIGHT = 24


def _default_weekdays() -> list[list[str]]:
    return [
        ["1F3864", "FFFFFF"],  # Mon
        ["305496", "FFFFFF"],  # Tue
        ["8EA9DB", "000000"],  # Wed
        ["B4C6E7", "000000"],  # Thu
        ["D9E1F2", "000000"],  # Fri
        ["002060", "FFFFFF"],  # Sat
        ["002060", "FFFFFF"],  # Sun
    ]


def normalize_hex(value: str) -> str:
    m = _HEX.match((value or "").strip())
    if not m:
        raise ValueError(f"Not a colour: {value!r} (use #RRGGBB)")
    return m.group(1).upper()


@dataclass
class MonthStyle:
    headers: list[str] = field(default_factory=lambda: list(HEADERS))
    header_bg: str = "1F497D"
    header_fg: str = "FFFFFF"
    border: str = "BFBFBF"
    weekdays: list[list[str]] = field(default_factory=_default_weekdays)  # [bg, fg] Mon..Sun
    column_widths: list[int] = field(default_factory=lambda: [15, 15, 35, 55, 15, 12])
    font: str = "Calibri"
    font_size: int = 11
    weekend_label: str = "Weekend"
    spacer_rows: bool = True
    merge_weekends: bool = True

    def colors(self, weekday: int) -> tuple[str, str]:
        bg, fg = self.weekdays[weekday]
        return bg, fg

    def validate(self) -> MonthStyle:
        if len(self.headers) != 6 or not all(h.strip() for h in self.headers):
            raise ValueError("All 6 column headers are required")
        self.headers = [h.strip()[:40] for h in self.headers]
        self.header_bg, self.header_fg, self.border = map(
            normalize_hex, (self.header_bg, self.header_fg, self.border)
        )
        if len(self.weekdays) != 7:
            raise ValueError("Colours for all 7 weekdays are required")
        self.weekdays = [[normalize_hex(bg), normalize_hex(fg)] for bg, fg in self.weekdays]
        if len(self.column_widths) != 6:
            raise ValueError("6 column widths are required")
        self.column_widths = [max(4, min(int(w), 120)) for w in self.column_widths]
        self.font = (self.font or "Calibri").strip()[:40] or "Calibri"
        self.font_size = max(6, min(int(self.font_size), 24))
        self.weekend_label = (self.weekend_label or "").strip()[:40]
        return self

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | None) -> MonthStyle:
        """Build from stored JSON; unknown keys are ignored, bad values fall back to defaults."""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known).validate()
        except (ValueError, TypeError, KeyError):
            return cls()


def hex_to_rgb(hex_color: str) -> dict[str, float]:
    """Google Sheets API colour object."""
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }
