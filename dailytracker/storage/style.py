"""Workbook look-and-feel shared by both backends (matches the original Daily.xlsx)."""

HEADER_BG = "1F497D"
HEADER_FG = "FFFFFF"
BORDER = "BFBFBF"

# weekday() -> (background, font colour)
WEEKDAY_COLORS = {
    0: ("1F3864", "FFFFFF"),  # Mon
    1: ("305496", "FFFFFF"),  # Tue
    2: ("8EA9DB", "000000"),  # Wed
    3: ("B4C6E7", "000000"),  # Thu
    4: ("D9E1F2", "000000"),  # Fri
    5: ("002060", "FFFFFF"),  # Sat
    6: ("002060", "FFFFFF"),  # Sun
}

COLUMN_WIDTHS = [15, 15, 35, 55, 15, 12]  # A..F, in Excel character units
ROW_HEIGHT = 22
SPACER_HEIGHT = 18
HEADER_HEIGHT = 24


def hex_to_rgb(hex_color: str) -> dict[str, float]:
    """Google Sheets API colour object."""
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }
