from datetime import date
from typing import List, final

import requests

from ..base import Integration, MeasurementTuple


@final
class Plausible(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "api_key": {"type": "string", "format": "password", "required": True},
            "site_id": {
                "type": "string",
                "required": True,
            },
            "metric": {
                "type": "string",
                "choices": sorted(
                    [
                        "visitors",
                        "pageviews",
                        "bounce_rate",
                        "visit_duration",
                        "events",
                        "visits",
                    ]
                ),
                "default": "visitors",
                "required": True,
            },
            "filters": {"type": "array", "items": {"type": "string"}},
        },
    }

    description = (
        "Daily visitors, pageviews, visits or events for your Plausible website."
    )

    def __enter__(self):
        assert (
            self.config is not None
        ), "Configuration is required in order to run this integration"
        self.r = requests.Session()
        self.r.headers.update({"Authorization": f"Bearer {self.config['api_key']}"})
        return self

    def can_backfill(self):
        return True

    def collect_past(self, date: date) -> MeasurementTuple:
        site_id = self.config["site_id"]
        period = "day"
        # See https://plausible.io/docs/metrics-definitions
        metric = self.config["metric"]
        filters: List[str] = self.config["filters"]

        url = f"https://plausible.io/api/v1/stats/aggregate"
        url += f"?site_id={site_id}"
        url += "&period=day&with_imported=true"
        # Plausible uses timezones defined in the plausible site config
        url += f"&date={date.strftime('%Y-%m-%d')}"
        url += f"&metrics={metric}"
        if filters:
            # See https://plausible.io/docs/stats-api#filtering
            url += f"&filters={';'.join(filters)}"
        response = self.r.get(url)
        response.raise_for_status()
        data = response.json()
        visitor_count = int(data["results"][metric]["value"])
        return MeasurementTuple(date=date, value=visitor_count)
