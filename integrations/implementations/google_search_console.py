import os
import urllib.parse
from datetime import date, timedelta
from typing import Dict, List, final

import requests

from ..models import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

ROW_LIMIT = 10000  # Number of rows to fetch at a time


@final
class GoogleSearchConsole(OAuth2Integration):
    # # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "site_url": {
                "type": "string",
                "required": True,
                "helpText": "This is a help text",
            },
            "metric": {
                "type": "string",
                "choices": ["position", "clicks", "impressions", "ctr"],
                "default": "visitors",
                "required": True,
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "dict",
                    "keys": {
                        "dimension": {
                            "type": "string",
                            "choices": [
                                "country",
                                "device",
                                "page",
                                "query",
                                "searchAppearance",
                            ],
                        },
                        "operator": {
                            "type": "string",
                            "choices": [
                                "contains",
                                "equals",
                                "notContains",
                                "notEquals",
                                "includingRegex",
                                "excludingRegex",
                            ],
                        },
                        "expression": {"type": "string"},
                    },
                },
            },
        },
    }

    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]

    def can_backfill(self):
        return True

    def _paginated_query(
        self, url, date_start: date, date_end: date, request_data: Dict, startRow=0
    ):
        response = self.session.post(
            url, json={**request_data, "rowLimit": ROW_LIMIT, "startRow": startRow}
        )
        response.raise_for_status()
        data = response.json()
        rows = data["rows"]
        if len(rows) < ROW_LIMIT:
            return rows
        else:
            return rows + self._paginated_query(
                url, date_start, date_end, request_data, startRow=startRow + len(rows)
            )

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Parameters
        site_url = self.config["site_url"]

        request_data = {
            # dates must be given in PT time
            "startDate": date_start.strftime("%Y-%m-%d"),
            "endDate": date_end.strftime("%Y-%m-%d"),
            "type": "web",
            "dataState": "all",  # One of 'final' or 'all' (which includes fresh data)
            "dimensions": ["date"],
            "dimensionFilterGroups": [
                {"groupType": "and", "filters": self.config["filters"]}
            ],
        }

        request_url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site_url)}/searchAnalytics/query"
        rows = self._paginated_query(request_url, date_start, date_end, request_data)

        return [
            MeasurementTuple(date=row["keys"][0], value=row["position"]) for row in rows
        ]
