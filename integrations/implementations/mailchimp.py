import time
from datetime import date, timedelta
from typing import List, Optional, final

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret


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
                    # "required": True,
                    "choices": sorted(
                        [{"title": l["name"], "value": l["id"]} for l in obj["lists"]],
                        key=lambda l: l["title"],
                    ),
                },
                "statistic": {
                    "type": "string",
                    "choices": sorted(
                        [
                            "emails_sent",
                            "unique_opens",
                            "recipient_clicks",
                            "hard_bounce",
                            "soft_bounce",
                            "subs",
                            "unsubs",
                            "other_adds",
                            "other_removes",
                        ]
                    ),
                    "required": True,
                },
            },
        }

    def can_backfill(self):
        return True

    def earliest_backfill(self) -> date:
        # 180 days according to the /activity endpoint
        return date.today() - timedelta(days=180)

    def _parse_date(self, date_str: str) -> date:
        s = date_str.split("-")
        return date(int(s[0]), int(s[1]), int(s[2]))

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        list_id = self.config["list"]
        statistic = self.config["statistic"]
        response = self.session.get(
            f"{self.api_endpoint}/3.0/lists/{list_id}/activity?count=1000"
        )
        response.raise_for_status()
        obj = response.json()
        measurements = (
            MeasurementTuple(date=self._parse_date(o["day"]), value=o[statistic])
            for o in obj["activity"]
        )
        return [m for m in measurements if m.date >= date_start and m.date <= date_end]
