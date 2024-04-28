from datetime import date, timedelta
from typing import Iterable, final

from requests_oauthlib import OAuth2Session

from integrations.base import MeasurementTuple, OAuth2Integration
from integrations.utils import batch_range_by_max_batch, get_secret


def collect_insights_for_account(
    session: OAuth2Session,
    access_token_override: str | None,
    account_id: str,
    metric: str,
    max_days: int,
    date_start: date,
    date_end: date,
) -> Iterable[MeasurementTuple]:
    if (date_end - date_start).days > max_days:
        yield from batch_range_by_max_batch(
            date_start=date_start,
            date_end=date_end,
            max_days=max_days,
            callable=lambda date_start, date_end: collect_insights_for_account(
                session,
                access_token_override,
                account_id,
                metric,
                max_days,
                date_start,
                date_end,
            ),
        )
    else:
        next_url = None
        processed_data_count = 0
        while True:
            # Request
            if not next_url:
                params = {
                    # 'access_token': access_token,
                    "period": "day",  # The aggregation period
                    "since": date_start.isoformat(),
                    "until": date_end.isoformat(),
                    "metric": metric,
                }
                if access_token_override:
                    params["access_token"] = access_token_override
                response = session.get(
                    f"https://graph.facebook.com/v19.0/{account_id}/insights",
                    params=params,
                )
            else:
                # Paging
                response = session.get(next_url)
            response.raise_for_status()
            obj = response.json()
            if not obj["data"]:
                return
            assert (
                len(obj["data"]) == 1
            ), f'Incorrect length of data returned ({len(obj["data"])}). Expected 1'
            values = obj["data"][0]["values"]
            for d in values:
                processed_data_count += 1
                dt = date_start + timedelta(days=processed_data_count)
                # For some reason the API forces us to page to future dates
                if dt <= date_end:
                    yield MeasurementTuple(date=dt, value=d["value"])

            # Only page if we expect more items
            expected_count = (date_end - date_start).days
            if len(values) >= expected_count:
                break
            else:
                # Attempt paging
                paging = obj["paging"]
                if "next" in paging:
                    next_url = paging["next"]
                else:
                    break


@final
class Facebook(OAuth2Integration):
    client_id = get_secret("FACEBOOK_APP_ID")
    client_secret = get_secret("FACEBOOK_APP_SECRET")
    authorization_url = "https://www.facebook.com/dialog/oauth"
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    refresh_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    scopes = [
        "public_profile,pages_read_engagement,pages_show_list,business_management,read_insights"
    ]
    authorize_extras = {
        "auth_type": "rerequest",  # re-ask for the declined permission
        "display": "page",
    }

    description = (
        "Collect metrics such as likes, impressions and reach from your Facebook page."
    )

    # Only the last two years of insights data is available.
    def earliest_backfill(self) -> date:
        return date.today().replace(year=date.today().year - 2)

    def can_backfill(self):
        return True

    def callable_config_schema(self):
        if not self.is_authorized:
            return self.config_schema
        # Returns all pages
        # See https://developers.facebook.com/docs/graph-api/reference/user/accounts/
        # See https://developers.facebook.com/docs/graph-api/reference/page/
        response = self.session.get(
            f"https://graph.facebook.com/v19.0/me/accounts?fields=id%2Cname%2Cusername"
        )
        response.raise_for_status()
        data = response.json()["data"]
        account_id_choices = sorted(
            [
                {
                    "title": account["name"],
                    "value": account["id"],
                }
                for account in data
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
                    "title": "Page",
                },
                "metric": {
                    "type": "string",
                    "required": True,
                    "choices": [
                        # https://developers.facebook.com/docs/graph-api/reference/page/insights/#availmetrics
                        # The number of times people have engaged with your posts through reactions, comments, shares and more.
                        {"title": "Post engagements", "value": "page_post_engagements"},
                        # The number of times your Page's posts entered a person's screen. Posts include statuses, photos, links, videos and more.
                        {
                            "title": "Post impressions",
                            "value": "page_posts_impressions",
                        },
                        # The number of people who had any of your Page's posts enter their screen. Posts include statuses, photos, links, videos and more.
                        {
                            "title": "Post reached users",
                            "value": "page_posts_impressions_unique",
                        },
                        # The total number of people who have liked your Page.
                        {"title": "Page likes", "value": "page_fans"},
                    ],
                },
            },
        }

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:
        # Get page access token
        response = self.session.get(
            f'https://graph.facebook.com/v19.0/{self.config["account_id"]}?fields=access_token'
        )
        response.raise_for_status()
        access_token = response.json()["access_token"]

        yield from collect_insights_for_account(
            session=self.session,
            access_token_override=access_token,
            account_id=self.config["account_id"],
            metric=self.config["metric"],
            # There cannot be more than 93 days (8035200 s) between since and from
            max_days=90,
            date_start=date_start,
            date_end=date_end,
        )
