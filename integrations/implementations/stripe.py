from datetime import date, datetime
from typing import Callable, Dict, Iterator, Optional, Tuple, final

import requests
from oauthlib.oauth2.rfc6749.parameters import parse_authorization_code_response
from requests.auth import HTTPBasicAuth

from ..base import MeasurementTuple, WebAuthIntegration
from ..utils import get_secret


@final
class Stripe(WebAuthIntegration):
    """
    The Stripe OAuth system doesn't require storing the token to query on behalf of the user,
    as seen in https://docs.stripe.com/stripe-apps/build-backend#using-stripe-apis
    This means we can simplify the implementation.
    """

    api_key = get_secret("STRIPE_API_KEY")
    client_id = get_secret("STRIPE_CLIENT_ID")
    authorization_url = "https://marketplace.stripe.com/oauth/v2/channellink*AY6Z9EIUHwAAAAeD%23EhcKFWFjY3RfMU1RWUdLQUdrWWk4dFF6Rg/authorize"

    description = "Track daily subscription revenue and customer count."

    _metric_choices = [
        {"title": "Customer count", "value": "customer_count", "can_backfill": True},
        {
            "title": "Subscription count (in trial)",
            "value": "subscription_count_trialing",
            "can_backfill": False,
        },
        {
            "title": "Subscription count (active)",
            "value": "subscription_count_active",
            "can_backfill": False,
        },
        {
            "title": "Subscriptions value (in trial)",
            "value": "subscriptions_value_trialing",
            "can_backfill": False,
        },
        {
            "title": "Subscriptions value (active)",
            "value": "subscriptions_value_active",
            "can_backfill": False,
        },
    ]

    config_schema = {
        "type": "dict",
        "keys": {
            "metric": {
                "type": "string",
                "choices": _metric_choices,
                "required": True,
            }
        },
    }

    def __init__(
        self,
        config: Optional[Dict],
        credentials: Dict,
        credentials_updater: Callable[[Dict], None],
    ):
        super().__init__(config, credentials, credentials_updater)
        self.stripeAccountId = credentials["stripe_user_id"]

    def __enter__(self):
        assert (
            self.stripeAccountId is not None
        ), "Stripe account ID is required in order to run this integration"
        self.r = requests.Session()
        self.r.headers.update({"Stripe-Account": self.stripeAccountId})
        self.r.auth = HTTPBasicAuth(self.api_key, "")
        return self

    @classmethod
    def get_authorization_uri_and_code_verifier(
        cls, state: str, authorize_callback_uri: str
    ) -> Tuple[str, Optional[str]]:
        # Make sure we force https:// instead of http://.
        return (
            f'{cls.authorization_url}?state={state}&client_id={cls.client_id}&redirect_uri={authorize_callback_uri.replace("http://", "https://")}',
            None,
        )

    @classmethod
    def process_callback(
        cls,
        uri: str,
        state: str,
        authorize_callback_uri: str,
        code_verifier: Optional[str] = None,
    ) -> dict:
        # Parse response
        params = parse_authorization_code_response(uri, state)
        assert "stripe_user_id" in params
        return params

    def paginated_request(
        self, url: str, params: Optional[dict] = None
    ) -> Iterator[dict]:
        r = self.r.get(url, params=params)
        r.raise_for_status()
        obj = r.json()
        yield from obj["data"]
        if obj["has_more"]:
            starting_after = obj["data"][-1]["id"]
            new_params = {**(params or {}), "starting_after": starting_after}
            yield from self.paginated_request(url, params=new_params)

    def _collect_past_customer_count(self, date: date) -> MeasurementTuple:
        start_time = datetime(
            year=date.year, month=date.month, day=date.day, tzinfo=None
        )
        end_time = start_time.replace(hour=23, minute=59, second=59)
        end_time_int = int(end_time.timestamp())
        return MeasurementTuple(
            date=date,
            value=len(
                list(
                    self.paginated_request(
                        f"https://api.stripe.com/v1/customers",
                        params={"created[lte]": end_time_int, "limit": 50},
                    )
                )
            ),
        )

    def _collect_latest_subscription_count(self, status: str) -> MeasurementTuple:
        # Valid status: incomplete, incomplete_expired, trialing, active, past_due, canceled, unpaid, or paused
        # See https://docs.stripe.com/api/subscriptions/object#subscription_object-status
        return MeasurementTuple(
            date=date.today(),
            value=len(
                list(
                    self.paginated_request(
                        f"https://api.stripe.com/v1/subscriptions",
                        params={"status": status, "limit": 50},
                    )
                )
            ),
        )

    def _collect_latest_subscriptions_value(self, status: str) -> MeasurementTuple:
        # Valid status: incomplete, incomplete_expired, trialing, active, past_due, canceled, unpaid, or paused
        # See https://docs.stripe.com/api/subscriptions/object#subscription_object-status
        return MeasurementTuple(
            date=date.today(),
            value=sum(
                [
                    subscription_item["price"]["unit_amount"]
                    * subscription_item["quantity"]
                    / 100
                    for subscription in self.paginated_request(
                        f"https://api.stripe.com/v1/subscriptions",
                        params={"status": status, "limit": 50},
                    )
                    for subscription_item in subscription["items"]["data"]
                ]
            ),
        )

    def _get_metric_config_for_key(self, metric_key):
        metric_key = self.config["metric"]
        metric_matches = [m for m in self._metric_choices if m["value"] == metric_key]
        assert metric_matches, f"Couldn't find metric {metric_key}"
        return metric_matches[0]

    def can_backfill(self):
        metric_config = self._get_metric_config_for_key(self.config["metric"])
        return metric_config.get("can_backfill", True)

    def collect_past(self, date: date) -> MeasurementTuple:
        """Will be called by `collect_past_range` when `can_backfill` returns True"""
        if self.config["metric"] == "customer_count":
            return self._collect_past_customer_count(date)
        raise KeyError(f"Couldn't find metric with value '{self.config['metric']}'")

    def collect_latest(self) -> MeasurementTuple:
        """Will be called by `collect_past_range` when `can_backfill` returns False"""

        if self.config["metric"].startswith("subscription_count_"):
            status = self.config["metric"].replace("subscription_count_", "")
            return self._collect_latest_subscription_count(status)

        if self.config["metric"].startswith("subscriptions_value_"):
            status = self.config["metric"].replace("subscriptions_value_", "")
            return self._collect_latest_subscriptions_value(status)

        raise KeyError(f"Couldn't find metric with value '{self.config['metric']}'")
