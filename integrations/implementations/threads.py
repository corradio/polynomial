from datetime import date, datetime
from typing import Optional, Tuple, final

import requests

from integrations.base import MeasurementTuple, OAuth2Integration
from integrations.utils import get_secret


@final
class Threads(OAuth2Integration):
    client_id = get_secret("THREADS_APP_ID")
    client_secret = get_secret("THREADS_APP_SECRET")
    authorization_url = "https://threads.net/oauth/authorize"
    token_url = "https://graph.threads.net/oauth/access_token"
    refresh_url = "https://graph.threads.net/oauth/refresh_access_token"
    scopes = ["threads_basic,threads_manage_insights"]
    description = "Collect metrics such as followers, impressions and reach from your Threads account."
    token_extras = {"include_client_id": True}

    # Only the last two years of insights data is available.
    def earliest_backfill(self) -> date:
        # 1712991600 according to https://developers.facebook.com/docs/threads/insights
        return date.fromtimestamp(1712991600)

    def can_backfill(self):
        return self.config.get("metric") != "followers_count"

    @classmethod
    def get_authorization_uri_and_code_verifier(
        cls, state: str, authorize_callback_uri: str
    ) -> Tuple[str, Optional[str]]:
        # Make sure we force https:// instead of http:// (as localhost testing is not allowed)
        url, _ = super(Threads, cls).get_authorization_uri_and_code_verifier(
            state, authorize_callback_uri
        )
        url = url.replace("=http%", "=https%")
        return url, _

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        response = self.session.get(
            f"https://graph.threads.net/v1.0/me/?fields=id,username,name"
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
        data = response.json()
        account_id_choices = [
            {
                "title": f'{data.get("name", "<unnamed>")} (@{data["username"]})',
                "value": data["id"],
            }
        ]

        return {
            "type": "dict",
            "keys": {
                "account_id": {
                    "type": "string",
                    "required": True,
                    "choices": account_id_choices,
                    "title": "Account",
                },
                "metric": {
                    "type": "string",
                    "required": True,
                    "choices": sorted(
                        [
                            # Note: other metrics are available at
                            # https://developers.facebook.com/docs/threads/insights
                            {"title": "Followers", "value": "followers_count"},
                            {"title": "Post likes", "value": "likes"},
                        ],
                        key=lambda o: o["title"],
                    ),
                },
            },
        }

    def collect_latest(self) -> MeasurementTuple:
        assert self.config["metric"] == "followers_count"
        response = self.session.get(
            f'https://graph.threads.net/v1.0/{self.config["account_id"]}/threads_insights?metric={self.config["metric"]}'
        )
        response.raise_for_status()
        data = response.json()["data"]
        return MeasurementTuple(
            date=date.today(), value=data[0]["total_value"]["value"]
        )

    def collect_past(self, date: date) -> MeasurementTuple:
        start_time = datetime(
            year=date.year, month=date.month, day=date.day, tzinfo=None
        )
        end_time = start_time.replace(hour=23, minute=59, second=59)
        since = int(start_time.timestamp())
        until = int(end_time.timestamp())
        response = self.session.get(
            f'https://graph.threads.net/v1.0/{self.config["account_id"]}/threads_insights?metric={self.config["metric"]}&since={since}&until={until}'
        )
        data = response.json()["data"]
        return MeasurementTuple(date=date, value=data[0]["total_value"]["value"])