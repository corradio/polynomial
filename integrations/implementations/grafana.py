from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, final

import requests

from ..base import Integration, MeasurementTuple
from ..utils import batch_range_by_max_batch, replace_null_with_nan

MAX_DAYS = 500


@final
class Grafana(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "api_key": {
                "type": "string",
                "format": "password",
                "required": True,
            },
            "datasource_uid": {
                "type": "string",
                "required": True,
            },
            "expression": {
                "type": "string",
                "required": True,
                "widget": "textarea",
            },
        },
    }

    def __enter__(self):
        assert (
            self.config is not None
        ), "Configuration is required in order to run this integration"
        self.r = requests.Session()
        self.r.headers.update({"Authorization": f"Bearer {self.config['api_key']}"})
        return self

    def can_backfill(self):
        return True

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

        expression = self.config["expression"]
        datasource_uid = self.config["datasource_uid"]
        # Grafana returns dates that represent the end of the day,
        # whereas we need dates at the beginning of the day
        dt_from = datetime.fromordinal(date_start.toordinal()) + timedelta(days=1)
        dt_to = datetime.fromordinal(date_end.toordinal()) + timedelta(days=1)
        payload = {
            "queries": [
                {
                    # TODO: Could be obtained by GET /api/datasources
                    "datasource": {
                        "uid": datasource_uid,
                    },
                    "expr": expression,
                    "refId": "A",
                    "interval": "1d",
                    "maxDataPoints": MAX_DAYS,  # Will error if we query more than can be returned
                    "format": "time_series",
                },
            ],
            "from": str(int(dt_from.timestamp() * 1000)),
            "to": str(int(dt_to.timestamp() * 1000)),
        }

        response = self.r.post(
            "https://electricitymap.grafana.net/api/ds/query", json=payload
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code == 400:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(
                    data["results"]["A"]["error"], response=e.response
                ) from e
            else:
                raise
        data = response.json()
        frames = data["results"]["A"]["frames"]
        if len(frames) == 0:
            return []
        assert len(frames) == 1, f"{len(frames)} returned series (expected only one)"
        frame = frames[0]
        if not frame["data"]["values"]:
            return []
        values: List[Optional[float]]
        timestamps, values = frame["data"]["values"]
        measurements = [
            MeasurementTuple(
                # timestamp represents value at the end of the day
                # we use a start-of-day convention
                date=datetime.utcfromtimestamp(timestamp / 1000).date()
                - timedelta(days=1),
                value=replace_null_with_nan(values[i]),
            )
            for i, timestamp in enumerate(timestamps)
        ]
        assert (
            measurements[0].date >= date_start
        ), f"{measurements[0].date} is before requested start {date_start}"
        assert (
            measurements[-1].date <= date_end
        ), f"{measurements[-1].date} is after requested end {date_end}"
        return measurements
