from datetime import date, datetime, timedelta, timezone
from typing import List, final
from zoneinfo import ZoneInfo

import requests

from ..models import Integration, MeasurementTuple


@final
class Twitter(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "api_key": {"type": "string", "format": "password", "required": True},
            "query": {
                "type": "string",
                "required": True,
                "helpText": "https://developer.twitter.com/en/docs/twitter-api/tweets/counts/integrate/build-a-query",
            },
        },
    }

    def __enter__(self):
        self.r = requests.Session()
        self.r.headers.update({"Authorization": f"Bearer {self.config['api_key']}"})
        return self

    def can_backfill(self):
        return True

    def earliest_backfill(self):
        # Twitter can only return the last 7*24 hours of data,
        # which means only the last 6 full days can be used
        return (datetime.now() - timedelta(days=6)).date()

    def collect_past(self, date: date) -> MeasurementTuple:
        # Twitter API expects datetimes in isoformat with UTC zone
        # TODO: pass user timezone here tzinfo=ZoneInfo(...)
        start_time = datetime(
            year=date.year, month=date.month, day=date.day, tzinfo=None
        )
        end_time = start_time.replace(hour=23, minute=59, second=59)
        start_time_utc_iso = (
            start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        end_time_utc_iso = (
            end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        print(start_time_utc_iso, end_time_utc_iso)
        response = self.r.get(
            "https://api.twitter.com/2/tweets/counts/recent",
            params={
                "query": self.config["query"],
                "start_time": start_time_utc_iso,
                "end_time": end_time_utc_iso,
            },
        )
        response.raise_for_status()
        data = response.json()
        mentions = data["meta"]["total_tweet_count"]
        return MeasurementTuple(date=date, value=mentions)
