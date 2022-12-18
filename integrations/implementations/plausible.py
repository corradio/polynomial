from datetime import date
from typing import List, final

import requests

from ..models import Integration, MeasurementTuple


@final
class Plausible(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "site_id": {
                "type": "string",
                "required": True,
                "helpText": "This is a help text",
            },
            "metric": {
                "type": "string",
                "choices": ["visitors"],
                "default": "visitors",
                "required": True,
            },
            "filters": {"type": "array", "items": {"type": "string"}},
        },
    }

    def can_backfill(self):
        return True

    def collect_past(self, date: date) -> MeasurementTuple:
        site_id = self.config["site_id"]
        period = "day"
        metric = self.config["metric"]
        filters: List[str] = self.config["filters"]

        r = requests.Session()
        r.headers.update(
            {"Authorization": f"Bearer {self.secrets['PLAUSIBLE_API_KEY']}"}
        )
        url = f"https://plausible.io/api/v1/stats/aggregate"
        url += f"?site_id={site_id}"
        url += "&period=day"
        # TODO: timezone?
        url += f"&date={date.strftime('%Y-%m-%d')}"
        url += f"&metrics={metric}"
        if filters:
            url += f"&filters={filters}"
        response = r.get(url)
        response.raise_for_status()
        visitor_count = int(response.json()["results"]["visitors"]["value"])
        return MeasurementTuple(date=date, value=visitor_count)
