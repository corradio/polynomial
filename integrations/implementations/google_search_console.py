import urllib.parse
from datetime import date
from typing import Dict, List, final

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

ROW_LIMIT = 10000  # Number of rows to fetch at a time


@final
class GoogleSearchConsole(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    description = "SEO position, clicks, impressions and CTR on Google Search."

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        response = self.session.get("https://www.googleapis.com/webmasters/v3/sites")
        response.raise_for_status()
        site_urls = [entry["siteUrl"] for entry in response.json().get("siteEntry", [])]
        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "site_url": {
                    "type": "string",
                    "required": True,
                    "choices": site_urls,
                },
                "metric": {
                    "type": "string",
                    "choices": sorted(["position", "clicks", "impressions", "ctr"]),
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
                                "required": True,
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
                                "required": True,
                            },
                            "expression": {
                                "type": "string",
                                "widget": "textarea",
                                "required": True,
                            },
                        },
                    },
                },
            },
        }

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
        rows: List = data["rows"]
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
        metric = self.config["metric"]

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

        request_url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote_plus(site_url)}/searchAnalytics/query"
        rows = self._paginated_query(request_url, date_start, date_end, request_data)

        return [
            # return NaN if the position is 0 as it means we don't know
            MeasurementTuple(
                date=date.fromisoformat(row["keys"][0]),
                value=row[metric] or float("nan"),
            )
            for row in rows
        ]
