from datetime import date, timedelta
from typing import Iterable, final

import requests
from oauthlib.oauth2 import InvalidGrantError

from integrations.base import MeasurementTuple, OAuth2Integration
from integrations.utils import get_secret

from .facebook import collect_insights_for_account


@final
class Instagram(OAuth2Integration):
    client_id = get_secret("FACEBOOK_APP_ID")
    client_secret = get_secret("FACEBOOK_APP_SECRET")
    authorization_url = "https://www.facebook.com/dialog/oauth"
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    refresh_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    scopes = [
        "public_profile,instagram_basic,instagram_manage_insights,pages_read_engagement,pages_show_list,business_management"
    ]
    authorize_extras = {
        "auth_type": "rerequest",  # re-ask for the declined permission
        "display": "page",
        "extras": '{"setup":{"channel":"IG_API_ONBOARDING"}}',
    }

    description = "Collect metrics such as followers, impressions and reach from your Instagram account."

    # Only the last two years of insights data is available.
    def earliest_backfill(self) -> date:
        return date.today() - timedelta(days=365 * 2)

    def can_backfill(self):
        return self.config["metric"] != "followers_count"

    def _call_endpoint(self, url: str) -> dict:
        response = self.session.get(url)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                data = e.response.json()
                if data["error"]["type"] == "OAuthException":
                    raise InvalidGrantError(data["error"]["message"]) from None
            raise
        return response.json()["data"]

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        # Returns all pages
        # See https://developers.facebook.com/docs/graph-api/reference/user/accounts/
        # See https://developers.facebook.com/docs/graph-api/reference/page/
        data = self._call_endpoint(
            f"https://graph.facebook.com/v19.0/me/accounts?fields=name%2Cusername%2Caccess_token%2Cinstagram_business_account"
        )
        account_id_choices = sorted(
            [
                {
                    "title": account["name"],
                    "value": account["instagram_business_account"]["id"],
                }
                for account in data
                if "instagram_business_account" in account  # Only keep insta accounts
            ],
            key=lambda d: d["title"],
        )

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
                    # https://developers.facebook.com/docs/instagram-api/reference/ig-user/insights#metrics-and-periods
                    "choices": sorted(
                        [
                            # Total number of unique users who have viewed at least one of the IG User's IG Media. Repeat views and views across different IG Media owned by the IG User by the same user are only counted as a single view. Includes ad activity generated through the API, Facebook ads interfaces, and the Promote feature.
                            {"title": "Reached users", "value": "reach"},
                            # Total number of new followers each day within the specified range (only when 100+ followers).
                            {"title": "New followers", "value": "follower_count"},
                            # Total followers (can't backfill)
                            {"title": "Followers", "value": "followers_count"},
                        ],
                        key=lambda o: o["title"],
                    ),
                },
            },
        }

    def collect_latest(self) -> MeasurementTuple:
        assert self.config["metric"] == "followers_count"
        response = self.session.get(
            f'https://graph.facebook.com/v19.0/{self.config["account_id"]}?fields=followers_count'
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                data = e.response.json()
                if data["error"]["type"] == "OAuthException":
                    raise InvalidGrantError(data["error"]["message"]) from None
            raise
        return MeasurementTuple(
            date=date.today(), value=response.json()["followers_count"]
        )

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:
        yield from collect_insights_for_account(
            session=self.session,
            access_token_override=None,
            account_id=self.config["account_id"],
            metric=self.config["metric"],
            max_days=30,
            date_start=date_start,
            date_end=date_end,
        )
