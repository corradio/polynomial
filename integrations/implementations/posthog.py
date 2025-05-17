from datetime import date, timedelta
from typing import Iterator, Optional, final

import requests

from ..base import Integration, MeasurementTuple, UserFixableError


@final
class PostHog(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "api_key": {"type": "string", "format": "password", "required": True},
            "endpoint": {
                "type": "string",
                "choices": [
                    "https://us.posthog.com",
                    "https://eu.posthog.com",
                ],
                "required": True,
            },
            "project_id": {"type": "string", "required": True},
            "query": {
                "type": "string",
                "widget": "textarea",
                "required": True,
                "helpText": "Use the HogQL language to query (see https://posthog.com/docs/hogql). Use %(date)s to insert the date requested by Polynomial.",
                "default": "SELECT COUNT(*) as value\nFROM events\nWHERE toStartOfDay(timestamp) == %(date)s",
            },
        },
    }

    description = "Use HogQL to query your PostHog database."
    protected_field_paths = [["api_key"]]

    def execute(
        self, query, query_date: Optional[date] = None
    ) -> Iterator[MeasurementTuple]:
        if query_date:
            query = query.replace(
                "%(date)s", f"toStartOfDay(toDateTime('{query_date.isoformat()}'))"
            )

        print(query)
        r = requests.post(
            f"{self.config['endpoint']}/api/projects/{self.config['project_id']}/query",
            headers={
                "Authorization": f'Bearer {self.config["api_key"]}',
                "Content-Type": "application/json",
            },
            json={"query": {"kind": "HogQLQuery", "query": query}},
        )
        r.raise_for_status()
        data = r.json()
        columns = data["columns"]
        results = data["results"]
        print(results)

        # Note: HogQL doesn't seem to support emitting a date (only a datetime)
        # so we don't allow making range queries (which require returning a date)
        if len(columns) != 1:
            raise UserFixableError("Only one column should be returned")

        return (
            MeasurementTuple(date=query_date or date.today(), value=float(r[0]))
            for r in results
        )

    def can_backfill(self):
        if not "query" in self.config:
            return False
        query = self.config["query"]
        return "%(date)s" in query

    def collect_latest(self) -> MeasurementTuple:
        query = self.config["query"]
        if self.can_backfill():
            return self.collect_past(date.today() - timedelta(days=1))
        else:
            return next(self.execute(query))

    def collect_past(self, date: date) -> MeasurementTuple:
        assert self.can_backfill()
        query = self.config["query"]
        return next(self.execute(query, query_date=date))
