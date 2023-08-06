import concurrent.futures
import csv
from datetime import datetime
from io import StringIO
from typing import final

import requests

from ..base import MeasurementTuple, OAuth2Integration, UserFixableError
from ..utils import get_secret


@final
class GoogleSheets(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    def callable_config_schema(self):
        # Get projects
        response = self.session.get(
            "https://cloudresourcemanager.googleapis.com/v1/projects"
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
        projects = [
            p for p in response.json()["projects"] if p["lifecycleState"] == "ACTIVE"
        ]
        # Get associate service accounts
        with concurrent.futures.ThreadPoolExecutor() as executor:
            service_account_choices = sorted(
                [
                    {
                        "title": f'{p["name"]}: {a["email"]}',
                        "value": a["email"],
                    }
                    for p, accounts in executor.map(
                        lambda p: (
                            p,
                            self.session.get(
                                f"https://iam.googleapis.com/v1/projects/{p['projectId']}/serviceAccounts"
                            )
                            .json()
                            .get("accounts", []),
                        ),
                        projects,
                    )
                    for a in accounts
                ],
                key=lambda d: d["title"],
            )
        return {
            "type": "dict",
            "keys": {
                "service_account": {
                    "type": "string",
                    "required": True,
                    "helpText": "Your account must have the right to impersonate selected service account",
                    "choices": service_account_choices,
                },
                "URL": {
                    "type": "string",
                    "required": True,
                },
                "date_field": {
                    "type": "string",
                    "required": True,
                    "helpText": "Name of the column from which dates will be extracted",
                },
                "value_field": {
                    "type": "string",
                    "required": True,
                    "helpText": "Name of the column from which values will be extracted",
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "dict",
                        "keys": {
                            "field": {"type": "string", "required": True},
                            "value": {"type": "string", "required": True},
                        },
                    },
                },
            },
        }

    def can_backfill(self):
        return False

    def collect_latest(self) -> MeasurementTuple:
        # Request an id token so we can query the final resource
        response = self.session.post(
            f'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{self.config["service_account"]}:generateIdToken',
            data={"includeEmail": True, "audience": self.config["URL"]},
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
        id_token = response.json()["token"]
        # Query
        response = requests.get(
            self.config["URL"],
            headers={"Authorization": f"Bearer {id_token}"},
        )
        response.raise_for_status()
        # Assume CSV for now
        assert (
            "text/csv;" in response.headers["content-type"]
        ), "Expected text/csv response content-header."
        f = StringIO(response.text)
        data = [
            MeasurementTuple(
                date=datetime.fromisoformat(row[self.config["date_field"]]).date(),
                value=float(row[self.config["value_field"]]),
            )
            for row in csv.DictReader(f, delimiter=";")
            if all([row[f["field"]] == f["value"] for f in self.config["filters"]])
        ]
        if len(data) > 1:
            raise UserFixableError("More than 1 matching value were found")
        if len(data) == 0:
            raise UserFixableError("No matching rows were found")
        return data[0]
