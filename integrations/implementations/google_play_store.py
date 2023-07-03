from datetime import date
from io import StringIO
from typing import Iterable, final

import numpy as np
import pandas as pd
import requests

from ..base import MeasurementTuple, OAuth2Integration, UserFixableError
from ..utils import batch_range_per_month, get_secret

"""
https://support.google.com/googleplay/android-developer/answer/139628?hl=en-GB&co=GENIE.Platform%3DDesktop#zippy=%2Cinstall-related-statistics

"""
METRICS = [
    {"title": "Daily Average Rating"},
    {"title": "Total Average Rating"},
    # An active device is one that has been turned on at least once in the past 30 days.
    {"title": "Active Device Installs"},
]


@final
class GooglePlayStore(OAuth2Integration):
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    refresh_url = "https://oauth2.googleapis.com/token"
    scopes = ["https://www.googleapis.com/auth/devstorage.read_only"]
    authorize_extras = {"access_type": "offline", "prompt": "consent"}

    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "developer_id": {
                "type": "string",
                "required": True,
                "helpText": "https://play.google.com/console/u/1/developers/<developer_id>/app-list",
            },
            "package_name": {
                "type": "string",
                "required": True,
                "helpText": "com.company.app",
            },
            "metric": {
                "type": "string",
                "choices": METRICS,
                "required": True,
            },
        },
    }

    def can_backfill(self):
        return True

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:

        year_start = date_start.year
        year_end = date_end.year
        month_start = date_start.month
        month_end = date_end.month

        if not (year_start == year_end and month_start == month_end):
            # Generate monthly ranges
            return batch_range_per_month(
                date_start=date_start,
                date_end=date_end,
                callable=self.collect_past_range,
            )

        yearmonth = f"{year_start}{month_start:02}"
        bucket = f"pubsite_prod_{self.config['developer_id']}"

        if "Rating" in self.config["metric"]:
            obj = f"stats%2Fratings%2Fratings_{self.config['package_name']}_{yearmonth}_overview.csv"
        elif "Installs" in self.config["metric"]:
            obj = f"stats%2Finstalls%2Finstalls_{self.config['package_name']}_{yearmonth}_overview.csv"
        else:
            raise NotImplementedError(f"Unknown metric '{self.config['metric']}'")
        column = self.config["metric"]

        request_url = (
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{obj}?alt=media"
        )
        response = self.session.get(request_url)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code in [400, 403]:
                # Try to explain to the user
                data = e.response.json()
                raise requests.HTTPError(data["error"]["message"]) from None
            if e.response.status_code == 404:
                # No data, simply return empty list
                return []
            else:
                raise
        df = pd.read_csv(
            StringIO(response.text), parse_dates=["Date"], index_col="Date"
        )
        if "Rating" in self.config["metric"]:
            # Replace "0" by np.nan
            df = df.replace(0, np.nan)
        df_filtered = df[
            (df.index >= date_start.isoformat()) & (df.index <= date_end.isoformat())
        ].sort_index()
        return (
            MeasurementTuple(date=index.to_pydatetime().date(), value=value)  # type: ignore[attr-defined]
            for index, value in df_filtered[column].items()
        )
