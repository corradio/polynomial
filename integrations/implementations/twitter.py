from datetime import date, datetime, timedelta, timezone
from typing import List, final
from zoneinfo import ZoneInfo

import requests

from ..base import Integration, MeasurementTuple
from ..utils import get_secret


@final
class Twitter(Integration):
    # Twitter uses the "app-only" credential mode
    # as we're only accessing public data
    api_key = get_secret("TWITTER_BEARER_TOKEN")
    code_challenge_method = "S256"

    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "query": {
                "type": "string",
                "required": True,
                "helpText": "https://developer.twitter.com/en/docs/twitter-api/tweets/counts/integrate/build-a-query",
            },
        },
    }

    def __enter__(self):
        super().__enter__()
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})
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
        response = self.session.get(
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
