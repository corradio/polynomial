import json
import time
from datetime import date, datetime
from typing import Any, Iterator, Optional, Tuple, final
from urllib import parse

from requests import Response

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret


def access_token_hook(r: Response) -> Response:
    token = json.loads(r.text)
    if "expires_at" not in token:
        # See https://docs.stripe.com/stripe-apps/api-authentication/oauth#refresh-access-token
        expires_in = 3600 - 1
        token["expires_at"] = time.time() + int(expires_in)
    r._content = json.dumps(token).encode()
    return r


def refresh_token_hook(r: Response) -> Response:
    token = json.loads(r.text)
    if "expires_at" not in token:
        # See https://docs.stripe.com/stripe-apps/api-authentication/oauth#refresh-access-token
        expires_in = 3600 * 24 * 365 - 1
        token["expires_at"] = time.time() + int(expires_in)
    r._content = json.dumps(token).encode()
    return r


def refresh_token_request_hook(token_url, headers, data) -> Tuple[Any, Any, Any]:
    # For some reason the `params` and `allow_redirects` requests params are passed
    # on to the `refresh_token` method. That shouldn't be the case.
    parsed_data = dict(parse.parse_qsl(data))
    if "params" in parsed_data:
        del parsed_data["params"]
    if "allow_redirects" in parsed_data:
        del parsed_data["allow_redirects"]
    new_data = parse.urlencode(parsed_data)
    # Ensure we authorize with our API key to ensure we can refresh the token
    return (
        token_url,
        {**headers, "Authorization": f"Bearer {get_secret('STRIPE_API_KEY')}"},
        new_data,
    )


@final
class Stripe(OAuth2Integration):
    client_id = get_secret("STRIPE_API_KEY")
    client_secret = ""
    authorization_url = "https://marketplace.stripe.com/oauth/v2/channellink*AY6Z9EIUHwAAAAeD%23EhcKFWFjY3RfMU1RWUdLQUdrWWk4dFF6Rg/authorize"
    token_url = "https://api.stripe.com/v1/oauth/token"
    refresh_url = "https://api.stripe.com/v1/oauth/token"

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

    """
        - tokens received don't have expired_at/in: they must be set manually
        - refresh_token API calls require passing Bearer (client_id) to /token endpoint.
          This happens automatically for `self.session.fetch_token` (through the `include_client_id` kwarg)
          but not for `self.session.refresh_token`. We therefore use a hook to manually set it.
    """
    compliance_hooks = {
        "access_token_response": access_token_hook,
        "refresh_token_response": refresh_token_hook,
        "refresh_token_request": refresh_token_request_hook,
    }

    @classmethod
    def get_authorization_uri_and_code_verifier(
        cls, state: str, authorize_callback_uri: str
    ) -> Tuple[str, Optional[str]]:
        # When issuing the autorization call, the client_id used must the client_id and not the
        # API key (which is used as client_id for all other token requests)
        # Also, make sure we force https:// instead of http://.
        client_id = get_secret("STRIPE_CLIENT_ID")
        return (
            f'{cls.authorization_url}?state={state}&client_id={client_id}&redirect_uri={authorize_callback_uri.replace("http://", "https://")}',
            None,
        )

    def paginated_request(
        self, url: str, params: Optional[dict] = None
    ) -> Iterator[dict]:
        r = self.session.get(url, params=params)
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
        start_time_int = int(start_time.timestamp())
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
