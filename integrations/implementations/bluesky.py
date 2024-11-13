from datetime import date, datetime, timedelta
from typing import final

import requests

from ..base import Integration, MeasurementTuple


def validate_http_response(response: requests.models.Response):
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        if (
            e.response is not None
            and e.response.status_code == 403
            and e.response.json()["reason"] == "client-not-enrolled"
        ):
            # This is a backend error due to insufficient privileges of the API token
            raise Exception("Inappropriate level of API access")
        # Other problems
        raise


@final
class Bluesky(Integration):
    description = "Mentions on Bluesky."

    def callable_config_schema(self):
        # Use https://bhch.github.io/react-json-form/playground
        config_schema = {
            "type": "dict",
            "keys": {
                "username": {
                    "type": "string",
                    "required": True,
                },
                "password": {
                    "type": "string",
                    "format": "password",
                    "required": True,
                },
                "metric": {
                    "type": "string",
                    "choices": [
                        {"title": "Mention count", "value": "query_mention_count"},
                        {"title": "Mention likes", "value": "query_mention_likes"},
                        {"title": "Mention replies", "value": "query_mention_replies"},
                        # The following require removing the query field
                        # {"title": "Followers", "value": "follower_count"}, # https://docs.bsky.app/docs/api/app-bsky-actor-get-profile
                    ],
                    "required": True,
                },
                "metric_query": {
                    "type": "string",
                    "required": True,
                    "helpText": "Search query string; syntax, phrase, boolean, and faceting is unspecified, but Lucene query syntax is recommended.",
                },
            },
        }
        # The following needs an auto-refresh..
        # See
        # if self.config.get("metric") == "query_mention_count":
        #     config_schema["keys"]["metric_query"] = {"type": "string", "required": True}
        return config_schema

    def __enter__(self):
        super().__enter__()
        username, password = self.config.get("username"), self.config.get("password")
        if username and password:
            r = requests.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": username, "password": password},
            )
            r.raise_for_status()
            accessJwt = r.json()["accessJwt"]
            self.session = requests.Session()
            self.session.headers.update({"Authorization": f"Bearer {accessJwt}"})
        return self

    def can_backfill(self):
        return True

    def collect_past(self, date: date) -> MeasurementTuple:

        # TODO: pass user timezone here tzinfo=ZoneInfo(...)
        start_time = datetime(
            year=date.year, month=date.month, day=date.day, tzinfo=None
        )
        end_time = start_time + timedelta(days=1)
        since = start_time.isoformat() + "Z"
        until = end_time.isoformat() + "Z"

        posts = []
        cursor = None
        while True:
            # # https://docs.bsky.app/docs/api/app-bsky-feed-search-posts
            params = {
                "q": '"Electricity Maps"',
                "since": since,  # Inclusive
                "until": until,  # Not inclusive
            }
            if cursor:
                params["cursor"] = cursor
            r = self.session.get(
                "https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            posts += data["posts"]
            cursor = data.get("cursor")
            if not cursor:
                break

        # Each post has an int being one of likeCount,replyCount,repostCount,quoteCount
        if self.config["metric"] == "query_mention_count":
            value = len(posts)
        elif self.config["metric"] == "query_mention_likes":
            value = sum([post["likeCount"] for post in posts])
        elif self.config["metric"] == "query_mention_replies":
            value = sum([post["replyCount"] for post in posts])
        else:
            raise KeyError(f"Unknown metric {self.config['metric']}")
        return MeasurementTuple(date=date, value=value)
