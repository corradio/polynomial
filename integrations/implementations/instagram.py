from datetime import date, timedelta
from typing import Iterable, final

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
        return True

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        # Returns all pages
        # See https://developers.facebook.com/docs/graph-api/reference/user/accounts/
        # See https://developers.facebook.com/docs/graph-api/reference/page/
        response = self.session.get(
            f"https://graph.facebook.com/v19.0/me/accounts?fields=name%2Cusername%2Caccess_token%2Cinstagram_business_account"
        )
        response.raise_for_status()
        data = response.json()["data"]
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

        # response = self.session.get(
        #     f'https://graph.facebook.com/v19.0/{data[1]["instagram_business_account"]["id"]}?fields=followers_count,username&access_token={data[1]["access_token"]}'
        # )
        # print(response.json())
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
                    "choices": [
                        # Total number of times the IG User's IG Media have been viewed. Includes ad activity generated through the API, Facebook ads interfaces, and the Promote feature. Does not include profile views.
                        {"title": "Impressions", "value": "impressions"},
                        # Total number of unique users who have viewed at least one of the IG User's IG Media. Repeat views and views across different IG Media owned by the IG User by the same user are only counted as a single view. Includes ad activity generated through the API, Facebook ads interfaces, and the Promote feature.
                        {"title": "Reached users", "value": "reach"},
                    ],
                },
            },
        }

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
