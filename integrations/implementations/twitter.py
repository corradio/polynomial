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
            "account": {
                "type": "string",
                "required": True,
            },
            "metric": {
                "type": "string",
                "choices": [
                    {"title": "Followers", "value": "follower_count"},
                    {"title": "Mentions", "value": "mention_count"},
                ],
                "required": True,
            },
        },
    }

    def __enter__(self):
        super().__enter__()
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})
        return self

    def can_backfill(self):
        # Only the `mention_count` metric can be backfilled
        return self.config["metric"] == "mention_count"

    def earliest_backfill(self):
        # Twitter can only return the last 7*24 hours of data,
        # which means only the last 6 full days can be used
        return (datetime.now() - timedelta(days=6)).date()

    def collect_latest(self):
        if not self.can_backfill():
            account = self.config["account"].replace("@", "")
            response = self.session.get(
                f"https://api.twitter.com/2/users/by/username/{account}?user.fields=public_metrics"
            )
            response.raise_for_status()
            data = response.json()["data"]
            mentions = data["public_metrics"]["followers_count"]
            return MeasurementTuple(date=date.today(), value=mentions)
        else:
            return super().collect_latest()

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
        # Make sure we never have the @ (this will allow us to support both cases)
        account = self.config["account"].replace("@", "")

        metric = self.config["metric"]
        if metric == "mention_count":
            response = self.session.get(
                "https://api.twitter.com/2/tweets/counts/recent",
                params={
                    # See https://developer.twitter.com/en/docs/twitter-api/tweets/counts/integrate/build-a-query
                    "query": f'"@{account}"',
                    "start_time": start_time_utc_iso,
                    "end_time": end_time_utc_iso,
                },
            )
            response.raise_for_status()
            data = response.json()
            mentions = data["meta"]["total_tweet_count"]
        else:
            raise NotImplementedError(
                f"Unknown metric {metric}. Are you sure it can backfill?"
            )

        return MeasurementTuple(date=date, value=mentions)
