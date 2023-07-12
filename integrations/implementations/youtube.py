import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, final

import requests

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

# See https://developers.google.com/youtube/analytics/metrics
METRICS = sorted(
    [
        "averageViewDuration",
        "comments",
        "dislikes",
        "likes",
        "shares",
        "estimatedMinutesWatched",
        "subscribersGained",
        "subscribersLost",
        "viewerPercentage",
        "views",
    ]
)

MAX_ROWS = 100


@final
class Youtube(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = [
        "https://www.googleapis.com/auth/youtube.readonly",
    ]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    # 'statistics': {'viewCount': '96160', 'subscriberCount': '443', 'hiddenSubscriberCount': False, 'videoCount': '20'}}

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        # Get all valid channels
        response = self.session.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "mine": True,
                # 'managedByMe': True,
                "part": "snippet",
            },
        )
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
        items = response.json().get("items", [])
        channel_choices = sorted(
            [
                {
                    "title": f'{item["snippet"]["title"]} ({item["id"]})',
                    "value": item["id"],
                }
                for item in items
            ],
            key=lambda d: d["title"],
        )
        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "channel": {
                    "type": "string",
                    "required": True,
                    "choices": channel_choices,
                },
                "metric": {
                    "type": "string",
                    "choices": METRICS,
                    "required": True,
                },
            },
        }

    def can_backfill(self):
        return True

    def _paginated_query(
        self,
        url,
        date_start: date,
        date_end: date,
        request_data: Dict,
        start_index=1,
    ):
        request_data = {
            **request_data,
            "startIndex": start_index,
            "maxResults": MAX_ROWS,
        }
        response = self.session.get(url, params=request_data)
        response.raise_for_status()
        data = response.json()
        rows = data["rows"]
        if len(rows) < MAX_ROWS:
            return rows
        else:
            return rows + self._paginated_query(
                url, date_start, date_end, request_data, start_index=len(rows) + 1
            )

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:
        # Parameters
        channel = self.config["channel"]
        metric = self.config["metric"]

        # Documentation:
        # https://youtubeanalytics.googleapis.com/v2/reports

        request_data = {
            "startDate": date_start.strftime("%Y-%m-%d"),
            "endDate": date_end.strftime("%Y-%m-%d"),
            "ids": f"channel=={channel}",
            "metrics": metric,
            "dimensions": "day",
            # TODO: add filters
        }

        request_url = f"https://youtubeanalytics.googleapis.com/v2/reports"
        rows = self._paginated_query(request_url, date_start, date_end, request_data)
        return (
            MeasurementTuple(
                date=datetime.strptime(row[0], "%Y-%m-%d").date(),
                value=float(row[1]),
            )
            for row in rows
        )

    def collect_latest(self) -> MeasurementTuple:
        # API returns delayed results
        # We therefore here call collect_past_range and
        # seek results in the past
        max_delay = 3
        results = self.collect_past_range(
            date_start=date.today() - timedelta(days=max_delay),
            date_end=date.today() - timedelta(days=1),
        )
        return list(results)[-1]
