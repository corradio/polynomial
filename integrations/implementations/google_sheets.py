import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, final

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

    def _serial_date_to_date(self, xldate: float) -> date:
        # See https://github.com/python-excel/xlrd/blob/f45f6304e1ca00d7268ab5ca9bac5103417e8be2/xlrd/xldate.py
        epoch = datetime(1899, 12, 30)
        # The integer part of the Excel date stores the number of days since
        # the epoch and the fractional part stores the percentage of the day.
        assert xldate != "", "Empty date detected in date column"
        days = int(xldate)
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
            if e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(data["error"]["message"]) from None
            else:
                raise
        data = response.json()["values"]
        header = data[0]
        data = data[1:]

        def get_cell(row, column_name):
            if not column_name in header:
                raise ValueError(
                    f"Unknown column {column_name}. Detected columns: {header}"
                )
            return row[header.index(column_name)]

        def try_convert_cell_to_float(cell_value):
            try:
                return float(cell_value)
            except ValueError as e:
                raise UserFixableError(
                    f'Could not convert cell value "{cell_value}" to number'
                ) from e

        # Parse data
        measurements = [
            MeasurementTuple(
                date=self._serial_date_to_date(get_cell(row, date_column)),
                value=try_convert_cell_to_float(get_cell(row, value_column)),
            )
            for row in data
            if all([get_cell(row, f["column"]) == f["value"] for f in filters])
        ]

        return [m for m in measurements if m.date >= date_start and m.date <= date_end]
