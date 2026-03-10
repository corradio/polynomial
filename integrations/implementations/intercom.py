from datetime import date, datetime, time, timedelta
from typing import final

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

METRICS = [{"title": "Conversations started", "value": "conversations_started"}]


@final
class Intercom(OAuth2Integration):
    client_id = get_secret("INTERCOM_CLIENT_ID")
    client_secret = get_secret("INTERCOM_CLIENT_SECRET")
    authorization_url = "https://app.intercom.com/oauth"
    token_url = "https://api.intercom.io/auth/eagle/token"
    refresh_url = None
    scopes = []

    description = "Track Intercom support conversations."

    config_schema = {
        "type": "dict",
        "keys": {
            "metric": {
                "type": "string",
                "choices": METRICS,
                "required": True,
            },
        },
    }

    def can_backfill(self) -> bool:
        return True

    def _count_conversations_for_date(self, d: date) -> int:
        start = int(datetime.combine(d, time.min).timestamp())
        end = int(datetime.combine(d + timedelta(days=1), time.min).timestamp())
        resp = self.session.post(
            "https://api.intercom.io/conversations/search",
            json={
                "query": {
                    "operator": "AND",
                    "value": [
                        {"field": "created_at", "operator": ">=", "value": start},
                        {"field": "created_at", "operator": "<", "value": end},
                    ],
                },
                "pagination": {"per_page": 1},
            },
            headers={"Accept": "application/json", "Intercom-Version": "2.11"},
        )
        resp.raise_for_status()
        return resp.json()["total_count"]

    def collect_past(self, date: date) -> MeasurementTuple:
        return MeasurementTuple(
            date=date, value=self._count_conversations_for_date(date)
        )
