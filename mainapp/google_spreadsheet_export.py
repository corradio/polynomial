import secrets
from datetime import date, datetime
from typing import Tuple, Union

import requests
from celery import shared_task
from django.http import HttpRequest
from django.urls import reverse
from requests_oauthlib import OAuth2Session

from integrations.utils import get_secret

from .models import Measurement, Metric, Organization

client_id = get_secret("GOOGLE_CLIENT_ID")
client_secret = get_secret("GOOGLE_CLIENT_SECRET")
authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
token_url = "https://oauth2.googleapis.com/token"
refresh_url = "https://oauth2.googleapis.com/token"
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
authorize_extras = {"access_type": "offline", "prompt": "consent"}


def authorize(request: HttpRequest) -> Tuple[str, str]:
    # Generate state to uniquely identify this request
    state = secrets.token_urlsafe(32)
    # Get uri
    client = OAuth2Session(
        client_id,
        scope=scopes,
        redirect_uri=request.build_absolute_uri(reverse("authorize-callback")),
    )
    uri, _ = client.authorization_url(
        authorization_url,
        state=state,
        **authorize_extras,
    )
    return uri, state


def process_authorize_callback(
    organization_id: int, uri: str, authorize_callback_uri: str, state: str
) -> str:
    client = OAuth2Session(client_id, redirect_uri=authorize_callback_uri)
    # Checks that the state is valid, will raise
    # MismatchingStateError if not.
    client.fetch_token(
        token_url,
        client_secret=client_secret,
        authorization_response=uri,
        state=state,
    )
    credentials = client.token
    org = Organization.objects.get(pk=organization_id)
    org.google_spreadsheet_export_credentials = credentials
    org.save()
    return reverse("organization_edit", args=[organization_id])


@shared_task()
def spreadsheet_export(
    spreadsheet_id,
    sheet_name,
    credentials,
    credentials_updater,
    measurement_filter_kwargs,
):
    measurements = Measurement.objects.filter(**measurement_filter_kwargs)

    session = OAuth2Session(
        client_id,
        scope=scopes,
        token=credentials,
        auto_refresh_url=refresh_url,
        # If the token gets refreshed, we will have to save it
        token_updater=credentials_updater,
        # For Google, the client_id+secret must be supplied for refresh tokens
        auto_refresh_kwargs={
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )

    def process_response(response):
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(data["error"]["message"]) from None
            else:
                raise

    # Create sheet if it doesn't exist
    # https://sheets.googleapis.com/v4/spreadsheets/spreadsheetId:batchUpdate
    try:
        request_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
        add_sheet_body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": sheet_name,
                        }
                    }
                }
            ]
        }
        response = session.post(request_url, json=add_sheet_body)
        process_response(response)
    except requests.HTTPError:
        pass

    # Clear sheet
    request_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}:clear"
    response = session.post(request_url)
    process_response(response)

    # Dump data
    params = {
        # See https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets.values/update
        "valueInputOption": "USER_ENTERED",
        "includeValuesInResponse": False,
    }

    def sheet_row_key(measurement: Measurement):
        return measurement.metric.name

    def sheet_datetime(dt: Union[date, datetime]):
        # This will format time in whatever timezone is given by the db
        return datetime.strftime(dt, "%Y-%m-%dT%H:%M:%S")

    # https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets.values#ValueRange
    update_values_body = {
        "values": [["updated_at", "datetime", "key", "value"]]
        + [
            # remember to replace None by empty string
            [
                sheet_datetime(m.updated_at),
                sheet_datetime(m.date),
                sheet_row_key(m),
                m.value,
            ]
            for m in measurements.order_by("-updated_at", "-date", "metric__name")
        ]
    }
    request_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}"
    response = session.put(request_url, params=params, json=update_values_body)
    process_response(response)
