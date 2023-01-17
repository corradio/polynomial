import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, final

import requests

from ..base import MeasurementTuple, OAuth2Integration
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
                "helpText": "...",
            },
            "sheet_range": {
                "type": "string",
                "required": True,
                "title": "Sheet name",
                "helpText": "...",
            },
            "date_column": {
                "type": "string",
                "required": True,
                "helpText": "...",
            },
            "value_column": {
                "type": "string",
                "required": True,
                "helpText": "...",
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
        days = int(xldate)
        print(
            epoch + timedelta(days, 0, 0, 0), (epoch + timedelta(days, 0, 0, 0)).date()
        )
        return (epoch + timedelta(days, 0, 0, 0)).date()

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
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise Exception(data["error"]["message"])
            else:
                raise
        data = response.json()["values"]
        header = data[0]
        data = data[1:]
        # Parse data
        measurements = [
            MeasurementTuple(
                date=self._serial_date_to_date(d[header.index(date_column)]),
                value=float(d[header.index(value_column)]),
            )
            for d in data
            if all([d[header.index(f["column"])] == f["value"] for f in filters])
        ]

        return [m for m in measurements if m.date >= date_start and m.date <= date_end]
