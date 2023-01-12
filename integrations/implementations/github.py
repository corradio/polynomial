from datetime import date, datetime, timedelta
from typing import Dict, List, Union, final

import requests

from ..base import MeasurementTuple, OAuth2Integration

REPO_METRICS: List[Dict[str, Union[str, int]]] = [
    {"title": "stars", "path": "", "response_prop": "stargazers_count"},
    {"title": "open issues", "path": "", "response_prop": "open_issues_count"},
    {"title": "watchers", "path": "", "response_prop": "watchers_count"},
    {"title": "forks", "path": "", "response_prop": "forks_count"},
    {"title": "subscribers", "path": "", "response_prop": "subscribers_count"},
    {
        "title": "page views",
        "path": "/traffic/views",
        "response_prop": "count",
        "backfill_days": 14,
    },
    {
        "title": "unique visitors",
        "path": "/traffic/views",
        "response_prop": "uniques",
        "backfill_days": 14,
    },
]
# Use title (the label shown on the form) as a fallback for value
REPO_METRICS = [{**v, "value": v.get("value", v["title"])} for v in REPO_METRICS]


@final
class Github(OAuth2Integration):
    client_id = "ee0d9a8ab68b56911699"
    client_secret = "7a03bf5fc46e3be41115df21857d78fe4d3512bd"
    authorization_url = "https://github.com/login/oauth/authorize"
    scopes = ["public_repo"]
    token_url = "https://github.com/login/oauth/access_token"
    refresh_url = None

    def callable_config_schema(self):
        r = self.session.get("https://api.github.com/user/repos")
        r.raise_for_status()
        data = r.json()
        repos = [item["full_name"] for item in data]
        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "repo_full_name": {
                    "type": "string",
                    "choices": sorted(repos),
                },
                "metric": {
                    "type": "string",
                    "choices": sorted(REPO_METRICS, key=lambda d: d["title"]),
                },
            },
        }

    def can_backfill(self):
        metric_config = self._get_metric_config_for_key(self.config["metric"])
        return "backfill_days" in metric_config

    def earliest_backfill(self):
        metric_config = self._get_metric_config_for_key(self.config["metric"])
        # Note: `backfill_days` excludes today
        return (datetime.now() - timedelta(days=metric_config["backfill_days"])).date()

    def _get_metric_config_for_key(self, metric_key):
        metric_key = self.config["metric"]
        metric_matches = [m for m in REPO_METRICS if m["value"] == metric_key]
        assert metric_matches, f"Couldn't find metric {metric_key}"
        return metric_matches[0]

    def collect_past_range(self, date_start, date_end) -> List[MeasurementTuple]:
        metric_key = self.config["metric"]
        metric_config = self._get_metric_config_for_key(metric_key)
        assert (
            int(metric_config.get("backfill_days", 0)) > 0
        ), f"Metric {metric_key} can't backfill"

        r = self.session.get(
            f"https://api.github.com/repos/{self.config['repo_full_name']}{metric_config['path']}"
        )
        r.raise_for_status()
        data = r.json()

        items = data[metric_config["path"].split("/")[-1]]
        # Filter to find associated timestamp (note: they are given in UTC)
        items = [
            # Parse dates
            {
                **item,
                "date": date.fromisoformat(item["timestamp"].replace("T00:00:00Z", "")),
            }
            for item in items
        ]
        return [
            MeasurementTuple(
                date=item["date"],
                value=item[metric_config["response_prop"]],
            )
            for item in items
            if item["date"] >= date_start and item["date"] <= date_end
        ]

    def collect_latest(self) -> MeasurementTuple:
        metric_key = self.config["metric"]
        metric_config = self._get_metric_config_for_key(metric_key)
        if "backfill_days" in metric_config:
            # This metric can backfill
            data = self.collect_past_range(
                date_start=date.today(), date_end=date.today()
            )
            assert len(data) == 1
            return data[0]
        # This metric can't backfill
        url = f"https://api.github.com/repos/{self.config['repo_full_name']}{metric_config['path']}"
        r = self.session.get(url)
        r.raise_for_status()
        data = r.json()
        return MeasurementTuple(
            date=date.today(), value=float(data[metric_config["response_prop"]])
        )
