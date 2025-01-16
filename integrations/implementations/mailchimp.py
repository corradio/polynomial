import time
from datetime import date, timedelta
from typing import List, Optional, final

from oauthlib.oauth2 import InvalidGrantError

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

METRICS = sorted(
    [
        # These are list-activity, can be collected historically
        # See https://mailchimp.com/developer/marketing/api/list-activity/
        {"value": "unique_opens", "title": "Unique opens", "endpoint": "list-activity"},
        {
            "value": "recipient_clicks",
            "title": "Recipient clicks",
            "endpoint": "list-activity",
        },
        {"value": "subs", "title": "New subscriptions", "endpoint": "list-activity"},
        {
            "value": "unsubs",
            "title": "New unsubscriptions",
            "endpoint": "list-activity",
        },
        # These are list stats, only live
        # See https://mailchimp.com/developer/marketing/api/lists/
        {"value": "member_count", "title": "Member count", "endpoint": "list-info"},
        {"value": "open_rate", "title": "Open rate", "endpoint": "list-info"},
        {"value": "click_rate", "title": "Click rate", "endpoint": "list-info"},
    ],
    key=lambda o: o["title"],
)


@final
class Mailchimp(OAuth2Integration):
    client_id = get_secret("MAILCHIMP_CLIENT_ID")
    client_secret = get_secret("MAILCHIMP_CLIENT_SECRET")
    authorization_url = "https://login.mailchimp.com/oauth2/authorize"
    token_url = "https://login.mailchimp.com/oauth2/token"
    # Mailchimp Marketing access tokens do not expire
    refresh_url = None
    token_extras = {"include_client_id": True}
    scopes = []

    description = (
        "Mailchimp list metrics such as subscribers, email opens and bounce rates."
    )

    @classmethod
    def process_callback(
        cls,
        uri: str,
        state: str,
        authorize_callback_uri: str,
        code_verifier: Optional[str] = None,
    ):
        credentials = super().process_callback(
            uri, state, authorize_callback_uri, code_verifier
        )
        # Mailchimp tokens never expire, which returns `expires_in=0` and causes
        # oauthlib to think it immediately expires. We therefore manually set an expiration date.
        credentials["expires_in"] = 100 * 365 * 24 * 3600  # 100 years
        credentials["expires_at"] = time.time() + int(credentials["expires_in"])
        return credentials

    def __enter__(self):
        super().__enter__()
        response = self.session.get("https://login.mailchimp.com/oauth2/metadata")
        response.raise_for_status()
        obj = response.json()
        if obj.get("error", "") == "invalid_token":
            raise InvalidGrantError(
                obj.get("error_description"), "Unknown error"
            ) from None
        self.api_endpoint = obj["api_endpoint"]
        return self

    def callable_config_schema(self):
        response = self.session.get(f"{self.api_endpoint}/3.0/lists?fields=lists")
        response.raise_for_status()
        obj = response.json()

        # Use https://rjsf-team.github.io/react-jsonschema-form/
        return {
            "type": "dict",
            "keys": {
                "list": {
                    "type": "string",
                    "required": True,
                    "choices": sorted(
                        [{"title": l["name"], "value": l["id"]} for l in obj["lists"]],
                        key=lambda l: l["title"],
                    ),
                },
                "statistic": {
                    "type": "string",
                    "choices": METRICS,
                    "required": True,
                },
            },
        }

    def can_backfill(self):
        if not "list" in self.config:
            return True
        if not "statistic" in self.config:
            return True
        list_id = self.config["list"]
        metric_key = self.config["statistic"]
        metric = next(m for m in METRICS if m["value"] == metric_key)
        if not metric:
            return True
        return metric["endpoint"] == "list-activity"

    def earliest_backfill(self) -> date:
        # 180 days according to the /activity endpoint
        return date.today() - timedelta(days=180)

    def _parse_date(self, date_str: str) -> date:
        s = date_str.split("-")
        return date(int(s[0]), int(s[1]), int(s[2]))

    def collect_latest(self) -> MeasurementTuple:
        list_id = self.config["list"]
        metric_key = self.config["statistic"]
        metric = next(m for m in METRICS if m["value"] == metric_key)
        assert metric["endpoint"] == "list-info"
        response = self.session.get(
            f"{self.api_endpoint}/3.0/lists/{list_id}?fields=stats"
        )
        response.raise_for_status()
        obj = response.json()
        print(obj["stats"])
        return MeasurementTuple(date=date.today(), value=obj["stats"][metric_key])

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        list_id = self.config["list"]
        metric_key = self.config["statistic"]
        metric = next(m for m in METRICS if m["value"] == metric_key)
        assert metric["endpoint"] == "list-activity"
        # Note: the endpoint doesn't support query by date. It can
        # paginate through the last 180 days though.
        batch_size = 100
        offset = 0
        measurements: List[MeasurementTuple] = []
        while True:
            response = self.session.get(
                f"{self.api_endpoint}/3.0/lists/{list_id}/activity?count={batch_size}&offset={offset}"
            )
            response.raise_for_status()
            obj = response.json()
            measurements += sorted(
                [
                    MeasurementTuple(
                        date=self._parse_date(o["day"]), value=o[metric_key]
                    )
                    for o in obj["activity"]
                ],
                key=lambda m: m.date,
                reverse=True,
            )
            # Check if we need to go back further
            if obj["activity"] and measurements[-1].date > date_start:
                # We must go further
                offset += len(obj["activity"])
            else:
                break

        return [m for m in measurements if m.date >= date_start and m.date <= date_end]
