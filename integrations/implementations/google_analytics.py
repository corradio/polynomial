import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, cast, final

import pandas as pd
import requests

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import batch_range_by_max_batch, fill_mesurement_range, get_secret

MAX_DAYS = 300  # Maximum number of days per paginated query
ROW_LIMIT = 10000  # Number of rows to fetch at a time
# See https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema
METRICS = sorted(["totalUsers", "sessions"])
DIMENSIONS = sorted(["countryId"])


@final
class GoogleAnalytics(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        # Get all valid GA ids
        response = self.session.get(
            "https://analyticsadmin.googleapis.com/v1alpha/accountSummaries"
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(
                    data["error"]["message"], response=e.response
                ) from None
            else:
                raise
        items = response.json()["accountSummaries"]
        property_id_choices = sorted(
            [
                {
                    "title": f"{property['displayName']} ({property['property'].split('/')[-1]})",
                    "value": property["property"].split("/")[-1],
                }
                for item in items
                for property in item["propertySummaries"]
            ],
            key=lambda d: d["title"],
        )
        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "property_id": {
                    "type": "string",
                    "required": True,
                    "choices": property_id_choices,
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

    def can_backfill(self):
        return True

    def _paginated_query(
        self,
        url,
        date_start: date,
        date_end: date,
        request_data: Dict,
        offset=0,
    ):
        if offset:
            request_data = {
                **request_data,
                "offset": offset,
            }
        response = self.session.post(url, json=request_data)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                # Try to explain to the user
                data = e.response.json()
                raise Exception(data["error"]["message"])
            else:
                raise
        data = response.json()
        rows = data.get("rows", [])
        if len(rows) < request_data["limit"]:
            return rows
        else:
            offset += data["rowCount"]
            return rows + self._paginated_query(
                url, date_start, date_end, request_data, offset=offset
            )

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:

        if (date_end - date_start).days > MAX_DAYS:
            return batch_range_by_max_batch(
                date_start=date_start,
                date_end=date_end,
                max_days=MAX_DAYS,
                callable=self.collect_past_range,
            )

        # Parameters
        property_id = self.config["property_id"]
        metric = self.config["metric"]

        # Documentation:
        # https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport

        request_data = {
            "dateRanges": [
                {
                    "startDate": date_start.strftime("%Y-%m-%d"),
                    "endDate": date_end.strftime("%Y-%m-%d"),
                },
            ],
            "dimensions": [{"name": "date"}],
            "dimensionFilter": {
                "andGroup": {
                    "expressions": [
                        {
                            "filter": {
                                "fieldName": filter["dimensionName"],
                                "stringFilter": {
                                    "matchType": filter["operator"],
                                    "value": filter["expression"],
                                },
                            }
                        }
                        for filter in self.config["filters"]
                    ],
                }
            },
            "metrics": [{"name": metric}],
            "limit": ROW_LIMIT,
        }

        # GA doesn't support empty filter groups
        if not self.config["filters"]:
            del request_data["dimensionFilter"]

        request_url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
        rows = self._paginated_query(request_url, date_start, date_end, request_data)
        if not rows:
            return []
        measurements = [
            MeasurementTuple(
                date=datetime.strptime(row["dimensionValues"][0]["value"], "%Y%m%d"),
                value=float(row["metricValues"][0]["value"]),
            )
            for row in rows
        ]
        # GA doesn't return data for rows that are 0
        return fill_mesurement_range(
            measurements, date_start=date_start, date_end=date_end, fill_value=0
        )
