from datetime import date, datetime, timedelta
from typing import List, final

import requests

from ..base import MeasurementTuple, OAuth2Integration, UserFixableError
from ..utils import get_secret


@final
class GoogleSheets(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    description = "Import any data from a Google Sheet."

    config_schema = {
        "type": "dict",
        "keys": {
            "spreadsheet_id": {
                "type": "string",
                "required": True,
                "helpText": "Can be found in a Google Sheets' URL https://docs.google.com/spreadsheets/d/<spreadsheet id>/edit#gid=0",
            },
            "sheet_range": {
                "type": "string",
                "required": True,
                "title": "Sheet name",
            },
            "date_column": {
                "type": "string",
                "required": True,
                "helpText": "Name of the column from which dates will be extracted",
            },
            "value_column": {
                "type": "string",
                "required": True,
                "helpText": "Name of the column from which values will be extracted",
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "dict",
                    "keys": {
                        "column": {"type": "string", "required": True},
                        "value": {"type": "string", "required": True},
                    },
                },
            },
        },
    }

    def can_backfill(self):
        return True

    def _try_convert_serial_date_to_date(self, xldate: str, row_index: int) -> date:
        # See https://github.com/python-excel/xlrd/blob/f45f6304e1ca00d7268ab5ca9bac5103417e8be2/xlrd/xldate.py
        epoch = datetime(1899, 12, 30)
        # The integer part of the Excel date stores the number of days since
        # the epoch and the fractional part stores the percentage of the day.
        try:
            days = int(xldate)
        except ValueError as e:
            raise UserFixableError(
                f'Could not convert cell value "{xldate}" to date at row {row_index + 1}.'
            ) from e
        return (epoch + timedelta(days, 0, 0, 0)).date()

    def collect_latest(self) -> MeasurementTuple:
        results = self.collect_past_range(
            date_start=date.min,
            date_end=date.today() - timedelta(days=1),
        )
        if not results:
            raise UserFixableError("No matching rows were found")
        return results[-1]

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Parameters
        spreadsheet_id = self.config["spreadsheet_id"]
        sheet_range = self.config["sheet_range"]
        date_column = self.config["date_column"]
        value_column = self.config["value_column"]
        filters = self.config["filters"]

        params = {
            # See https://developers.google.com/sheets/api/reference/rest/v4/DateTimeRenderOption
            "dateTimeRenderOption": "SERIAL_NUMBER",
            "valueRenderOption": "UNFORMATTED_VALUE",
        }

        request_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}"
        response = self.session.get(request_url, params=params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(
                    data["error"]["message"], response=e.response
                ) from None
            else:
                raise
        data = response.json()["values"]
        header = data[0]
        data = data[1:]

        def get_cell(row: dict, column_name: str) -> str:
            if not column_name in header:
                raise UserFixableError(
                    f"Column '{column_name}' wasn't found in the header (should be one of {header})."
                )
            try:
                return row[header.index(column_name)]
            except IndexError:
                # This can happen if a row only has the first column but rest is empty values:
                # the row vector will be shorter. We simply mark this as empty.
                return ""

        def try_convert_cell_to_float(cell_value: str, row_index: int) -> float:
            try:
                return float("nan") if cell_value == "" else float(cell_value)
            except ValueError as e:
                raise UserFixableError(
                    f'Could not convert cell value "{cell_value}" to number at row {row_index + 1}'
                ) from e

        # Parse data
        measurements = [
            MeasurementTuple(
                date=self._try_convert_serial_date_to_date(
                    get_cell(row, date_column), row_index
                ),
                value=try_convert_cell_to_float(get_cell(row, value_column), row_index),
            )
            for row_index, row in enumerate(data)
            if all([get_cell(row, f["column"]) == f["value"] for f in filters])
        ]

        return [m for m in measurements if m.date >= date_start and m.date <= date_end]
