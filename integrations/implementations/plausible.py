from datetime import date
from typing import List

import requests

from integrations.integration import Integration, Measurement


class Plausible(Integration):
    def collect_past(self, date: date) -> Measurement:
        site_id = "app.electricitymaps.com"
        period = "day"
        metric = "visitors"
        filters: List[str] = []

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
        print(url)
        if filters:
            url += f"&filters={filters}"
        response = r.get(url)
        response.raise_for_status()
        visitor_count = int(response.json()["results"]["visitors"]["value"])
        return Measurement((date, visitor_count))
