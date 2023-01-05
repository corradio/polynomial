import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, final

import requests

from ..models import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

ROW_LIMIT = 10000  # Number of rows to fetch at a time
# See https://developers.google.com/analytics/devguides/reporting/core/dimsmets
METRICS = sorted(["ga:users", "ga:sessions"])
DIMENSIONS = sorted(["ga:countryIsoCode"])


@final
class GoogleAnalytics(OAuth2Integration):
    # # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "view_id": {
                "type": "string",
                "required": True,
                "helpText": "This is a help text",
            },
            "metric": {
                "type": "string",
                "choices": METRICS,
                "required": True,
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "dict",
                    "keys": {
                        "dimensionName": {
                            "type": "string",
                            "choices": DIMENSIONS,
                        },
                        "operator": {
                            "type": "string",
                            "choices": sorted(
                                [
                                    "REGEXP",
                                    "BEGINS_WITH",
                                    "ENDS_WITH",
                                    "PARTIAL",
                                    "EXACT",
                                    "NUMERIC_EQUAL",
                                    "NUMERIC_GREATER_THAN",
                                    "NUMERIC_LESS_THAN",
                                    "IN_LIST",  # Not supported as it would require multiple expressions
                                ]
                            ),
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
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]

    def can_backfill(self):
        return True

    def _paginated_query(
        self,
        url,
        date_start: date,
        date_end: date,
        request_data: Dict,
        nextPageToken=None,
    ):
        if nextPageToken:
            request_data = {
                "reportRequests": [
                    {
                        **request_data["reportRequests"][0],
                        "pageToken": nextPageToken,
                    }
                ]
            }
        response = self.session.post(url, json=request_data)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                # Try to explain to the user
                data = e.response.json()
                print(data)
                raise Exception(data["error"]["message"])
            else:
                raise
        data = response.json()
        nextPageToken = data["reports"][0].get("nextPageToken")
        rows = data["reports"][0]["data"].get("rows", [])
        if not nextPageToken:
            return rows
        else:
            return rows + self._paginated_query(
                url, date_start, date_end, request_data, nextPageToken=nextPageToken
            )

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Parameters
        view_id = self.config["view_id"]
        metric = self.config["metric"]

        # Documentation:
        # https://developers.google.com/analytics/devguides/reporting/core/v4/rest/v4/reports/batchGet#ReportRequest

        request_data = {
            "reportRequests": [
                {
                    "viewId": view_id,
                    "dateRanges": [
                        {
                            "startDate": date_start.strftime("%Y-%m-%d"),
                            "endDate": date_end.strftime("%Y-%m-%d"),
                        },
                    ],
                    "dimensions": [{"name": "ga:date"}],
                    "dimensionFilterClauses": [
                        {
                            "operator": "and",
                            "filters": [
                                {
                                    "dimensionName": filter["dimensionName"],
                                    "operator": filter["operator"],
                                    "expressions": [filter["expression"]],
                                }
                                for filter in self.config["filters"]
                            ],
                        }
                    ],
                    "metrics": [{"expression": metric}],
                    "pageSize": ROW_LIMIT,
                },
            ],
        }

        request_url = f"https://analyticsreporting.googleapis.com/v4/reports:batchGet"
        rows = self._paginated_query(request_url, date_start, date_end, request_data)
        return [
            MeasurementTuple(
                date=datetime.strptime(row["dimensions"][0], "%Y%m%d").date(),
                value=float(row["metrics"][0]["values"][0]),
            )
            for row in rows
        ]
