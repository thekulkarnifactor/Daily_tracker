"""Google Sheets backend (production).

The app authenticates as a Google service account. Share your "Daily" Google
Sheet with the service account's ``client_email`` (Editor access) and set
``GOOGLE_SHEET_ID`` to the ID in the sheet URL.
"""

from __future__ import annotations

import datetime as dt
import functools
import logging

import gspread
from gspread.http_client import BackOffHTTPClient
from gspread.utils import DateTimeOption, ValueInputOption, ValueRenderOption

from ..model import HEADERS, date_to_serial, month_layout, parse_tab_name, placeholder_values, tab_name
from . import style
from .base import RawRow, Storage, StorageError

log = logging.getLogger(__name__)


def _wrap_errors(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except StorageError:
            raise
        except gspread.exceptions.SpreadsheetNotFound as exc:
            raise StorageError(
                "Google Sheet not found. Check GOOGLE_SHEET_ID and share the sheet with "
                f"{self.service_account_email} as an Editor."
            ) from exc
        except gspread.exceptions.APIError as exc:
            raise StorageError(f"Google Sheets API error: {exc}") from exc
        except Exception as exc:
            raise StorageError(f"Google Sheets request failed: {exc}") from exc

    return wrapper


class SheetsStorage(Storage):
    name = "sheets"

    def __init__(self, sheet_id: str, credentials: dict, cache_ttl: int = 60) -> None:
        super().__init__(cache_ttl)
        if not credentials:
            raise StorageError("Google service account credentials missing. Set GOOGLE_SERVICE_ACCOUNT_JSON.")
        self.sheet_id = sheet_id
        self.service_account_email = credentials.get("client_email", "the service account")
        self._client = gspread.service_account_from_dict(
            credentials,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],  # least privilege: no Drive access
            http_client=BackOffHTTPClient,
        )
        self._spreadsheet = None

    @property
    def spreadsheet(self) -> gspread.Spreadsheet:
        if self._spreadsheet is None:
            self._spreadsheet = self._client.open_by_key(self.sheet_id)
        return self._spreadsheet

    def _ws(self, tab: str) -> gspread.Worksheet:
        return self.spreadsheet.worksheet(tab)

    # --------------------------------------------------------------- hooks

    @_wrap_errors
    def _list_tabs(self) -> list[str]:
        return [ws.title for ws in self.spreadsheet.worksheets()]

    @_wrap_errors
    def _read_rows(self, tab: str) -> list[RawRow]:
        values = self._ws(tab).get(
            "A2:F",
            value_render_option=ValueRenderOption.unformatted,
            date_time_render_option=DateTimeOption.serial_number,
        )
        return [(idx, list(row)) for idx, row in enumerate(values, start=2)]

    @_wrap_errors
    def _write_rows(self, tab: str, rows: dict[int, list[str]]) -> None:
        data = [{"range": f"B{row}:F{row}", "values": [values]} for row, values in rows.items()]
        # RAW so text like "=SUM(...)" or "+91..." is stored as typed, never as a formula.
        self._ws(tab).batch_update(data, value_input_option=ValueInputOption.raw)

    @_wrap_errors
    def _append_row(self, tab: str, date: dt.date, values: list[str]) -> int:
        ws = self._ws(tab)
        rows = self._read_rows(tab)
        last = max((r for r, cells in rows if any(c not in ("", None) for c in cells)), default=1)
        row_no = last + 1
        if row_no > ws.row_count:
            ws.add_rows(row_no - ws.row_count)
        ws.update(
            values=[[date_to_serial(date), *values]],
            range_name=f"A{row_no}:F{row_no}",
            value_input_option=ValueInputOption.raw,
        )
        ws.format(f"A{row_no}", {"numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}})
        return row_no

    @_wrap_errors
    def _create_tab(self, year: int, month: int, prefill) -> str:
        prefill = prefill or {}
        name = tab_name(year, month)
        layout = month_layout(year, month)
        values: list[list] = [HEADERS]
        for d in layout:
            if d is None:
                values.append([""] * 6)
            else:
                values.append([date_to_serial(d), *(prefill.get(d) or placeholder_values(d))])

        ws = self.spreadsheet.add_worksheet(
            title=name, rows=len(values), cols=6, index=self._insert_index(year, month)
        )
        ws.update(values=values, range_name="A1", value_input_option=ValueInputOption.raw)
        self.spreadsheet.batch_update({"requests": self._format_requests(ws.id, layout)})
        log.info("created tab %s", name)
        return name

    # ------------------------------------------------------------- helpers

    def _insert_index(self, year: int, month: int) -> int:
        """Position that keeps tabs in chronological order."""
        tabs = self._list_tabs()
        for idx, title in enumerate(tabs):
            parsed = parse_tab_name(title)
            if parsed and parsed > (year, month):
                return idx
        return len(tabs)

    @staticmethod
    def _format_requests(sheet_id: int, layout: list[dt.date | None]) -> list[dict]:
        def grid(r0, r1, c0=0, c1=6):
            return {
                "sheetId": sheet_id,
                "startRowIndex": r0,
                "endRowIndex": r1,
                "startColumnIndex": c0,
                "endColumnIndex": c1,
            }

        def cell_format(bg, fg, bold=False, h_align="LEFT"):
            return {
                "backgroundColor": style.hex_to_rgb(bg),
                "textFormat": {
                    "foregroundColor": style.hex_to_rgb(fg),
                    "fontFamily": "Calibri",
                    "fontSize": 11,
                    "bold": bold,
                },
                "verticalAlignment": "MIDDLE",
                "horizontalAlignment": h_align,
            }

        fields = "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,horizontalAlignment)"
        requests: list[dict] = [
            {
                "repeatCell": {
                    "range": grid(0, 1),
                    "cell": {
                        "userEnteredFormat": cell_format(
                            style.HEADER_BG, style.HEADER_FG, bold=True, h_align="CENTER"
                        )
                    },
                    "fields": fields,
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
        for idx, width in enumerate(style.COLUMN_WIDTHS):
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": idx,
                            "endIndex": idx + 1,
                        },
                        "properties": {"pixelSize": int(width * 7.5)},
                        "fields": "pixelSize",
                    }
                }
            )

        for offset, d in enumerate(layout, start=1):  # row index 0 is the header
            if d is None:
                continue
            bg, fg = style.WEEKDAY_COLORS[d.weekday()]
            requests.append(
                {
                    "repeatCell": {
                        "range": grid(offset, offset + 1),
                        "cell": {"userEnteredFormat": cell_format(bg, fg)},
                        "fields": fields,
                    }
                }
            )
            for col in (0, 5):  # centre Date and Status
                requests.append(
                    {
                        "repeatCell": {
                            "range": grid(offset, offset + 1, col, col + 1),
                            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                            "fields": "userEnteredFormat.horizontalAlignment",
                        }
                    }
                )
            if d.weekday() == 6 and offset >= 2 and layout[offset - 2] is not None:
                requests.append(
                    {
                        "mergeCells": {
                            "range": grid(offset - 1, offset + 1, 2, 6),
                            "mergeType": "MERGE_COLUMNS",
                        }
                    }
                )

        requests.append(
            {
                "repeatCell": {
                    "range": grid(1, len(layout) + 1, 0, 1),
                    "cell": {
                        "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}}
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )
        border = {"style": "SOLID", "color": style.hex_to_rgb(style.BORDER)}
        requests.append(
            {
                "updateBorders": {
                    "range": grid(0, len(layout) + 1),
                    "top": border,
                    "bottom": border,
                    "left": border,
                    "right": border,
                    "innerHorizontal": border,
                    "innerVertical": border,
                }
            }
        )
        return requests
