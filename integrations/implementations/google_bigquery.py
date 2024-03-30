from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, final

import requests

from ..base import MeasurementTuple, OAuth2Integration, UserFixableError
from ..utils import get_secret


@final
class GoogleBigQuery(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = [
        "https://www.googleapis.com/auth/cloud-platform.read-only",
        "https://www.googleapis.com/auth/bigquery.readonly",
    ]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    description = "Use SQL to query Google BigQuery."

    def _parse_response(self, response):
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
        return response.json()

    def callable_config_schema(self):
        # Get projects
        projects = [
            {
                "title": f"{organization['displayName']}/{project['displayName']} ({project['projectId']})",
                "value": project["projectId"],
            }
            for organization in self._parse_response(
                self.session.post(
                    "https://cloudresourcemanager.googleapis.com/v1/organizations:search"
                )
            )["organizations"]
            for project in self._parse_response(
                self.session.get(
                    "https://cloudresourcemanager.googleapis.com/v3/projects",
                    params={"parent": organization["name"], "showDeleted": False},
                )
            )["projects"]
        ]

        return {
            "type": "dict",
            "keys": {
                "project_id": {
                    "type": "string",
                    "required": True,
                    "choices": sorted(projects, key=lambda r: r["title"]),
                },
                "sql_query_template": {
                    "type": "string",
                    "widget": "textarea",
                    "required": True,
                    "helpText": "Use @date_start and @date_end to insert requested start and end dates in SQL Query. Note the dates are inclusive.",
                    "default": "SELECT CURRENT_DATE() as date, 1 as value",
                },
            },
        }

    def can_backfill(self):
        if not "sql_query_template" in self.config:
            return False
        sql_query_template = self.config["sql_query_template"]
        return "@date_start" in sql_query_template and "@date_end" in sql_query_template

    def _query(
        self,
        sql_query: str,
        project_id: str,
        date_start: Optional[date] = None,
        date_end: Optional[date] = None,
    ) -> List[MeasurementTuple]:
        date_start_str = date_start.strftime("%Y-%m-%d") if date_start else None
        date_end_str = date_end.strftime("%Y-%m-%d") if date_end else None
        data = self._parse_response(
            self.session.post(
                f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/queries",
                json={
                    "query": sql_query,
                    "useLegacySql": False,
                    "parameterMode": "NAMED",
                    "queryParameters": [
                        {
                            "name": "date_start",
                            "parameterType": {"type": "DATE"},
                            "parameterValue": {"value": date_start_str},
                        },
                        {
                            "name": "date_end",
                            "parameterType": {"type": "DATE"},
                            "parameterValue": {"value": date_end_str},
                        },
                    ],
                },
            )
        )
        fields = data["schema"]["fields"]
        rows = (
            {fields[i]["name"]: f["v"] for i, f in enumerate(row["f"])}
            for row in data.get("rows", [])
        )
        return [
            MeasurementTuple(date=_date_getter(row), value=_value_getter(row))
            for row in rows
        ]

    def collect_latest(self) -> MeasurementTuple:
        sql_query_template = self.config["sql_query_template"]
        project_id = self.config["project_id"]
        if self.can_backfill():
            return self.collect_past(date.today() - timedelta(days=1))
        else:
            return self._query(sql_query_template, project_id)[0]

    def collect_past(self, date: date) -> MeasurementTuple:
        return self.collect_past_range(date_start=date, date_end=date)[0]

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        assert self.can_backfill()
        sql_query_template = self.config["sql_query_template"]
        project_id = self.config["project_id"]
        return self._query(
            sql_query_template, project_id, date_start=date_start, date_end=date_end
        )


def _date_getter(row: dict) -> date:
    try:
        dt = datetime.strptime(row["date"], "%Y-%m-%d").date()
    except KeyError as e:
        raise UserFixableError(
            f"Date column {e} is missing from results. Did you rename it correctly using SELECT <yourfield> AS date?"
        )
    if not isinstance(dt, date):
        raise UserFixableError(
            f"Expected data from column 'date' to be a date. Received {type(dt).__name__} instead."
        )
    return dt


def _value_getter(row: dict) -> float:
    try:
        value = row["value"]
        # Attempt conversions
        if (
            isinstance(value, int)
            or isinstance(value, Decimal)
            or (isinstance(value, str) and value.isnumeric())
        ):
            value = float(value)
    except KeyError as e:
        raise UserFixableError(
            f"Value column {e} is missing from results. Did you rename it correctly using SELECT <yourfield> AS value?"
        )
    if not isinstance(value, float):
        raise UserFixableError(
            f"Expected data from column 'value' to be a number. Received {type(value).__name__} instead."
        )
    return value
