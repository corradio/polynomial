from datetime import date
from typing import final

from integrations.utils import get_secret

from ..base import MeasurementTuple, OAuth2Integration


@final
class Hubspot(OAuth2Integration):
    client_id = get_secret("HUBSPOT_CLIENT_ID")
    client_secret = get_secret("HUBSPOT_CLIENT_SECRET")
    authorization_url = "https://app-eu1.hubspot.com/oauth/authorize"
    token_url = "https://api.hubapi.com/oauth/v1/token"
    refresh_url = "https://api.hubapi.com/oauth/v1/token"
    scopes = ["crm.lists.read"]

    token_extras = {"include_client_id": True}

    description = "Import data from your Hubspot account."

    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "list_name": {"type": "string", "required": True},
        },
    }

    def can_backfill(self):
        return False

    def collect_latest(self) -> MeasurementTuple:
        list_name = self.config["list_name"]
        request_url = (
            f"https://api.hubapi.com/crm/v3/lists/object-type-id/0-1/name/{list_name}"
        )
        response = self.session.get(request_url)
        response.raise_for_status()
        data = response.json()
        return MeasurementTuple(date=date.today(), value=data["list"]["size"])
