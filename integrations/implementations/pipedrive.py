import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, final

import requests

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

BASE_URL = "https://api.pipedrive.com/api/v1"


@final
class Pipedrive(OAuth2Integration):
    client_id = get_secret("PIPEDRIVE_CLIENT_ID")
    client_secret = get_secret("PIPEDRIVE_CLIENT_SECRET")
    authorization_url = "https://oauth.pipedrive.com/oauth/authorize"
    token_url = "https://oauth.pipedrive.com/oauth/token"
    refresh_url = "https://oauth.pipedrive.com/oauth/token"
    scopes = ["base", "deals:read"]

    def callable_config_schema(self):
        # Get all pipelines
        response = self.session.get(
            f"{BASE_URL}/pipelines",
        )
        response.raise_for_status()
        data = response.json()["data"]
        pipeline_choices = sorted(
            [
                {"title": item["name"], "value": item["id"]}
                for item in data
                if item["active"] is True
            ],
            key=lambda d: d["title"],
        )

        # Get all stages
        response = self.session.get(
            f"{BASE_URL}/stages",
        )
        response.raise_for_status()
        data = response.json()["data"]
        stage_choices = sorted(
            [
                {
                    "title": f"{item['pipeline_name']} / {item['name']}",
                    "value": item["id"],
                    "order_nr": item["order_nr"],
                }
                for item in data
                if item["active_flag"] is True
            ],
            key=lambda d: d["order_nr"],
        )

        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "metric": {
                    "type": "string",
                    "choices": [
                        {"title": "Number of deals", "value": "count"},
                    ],
                    "required": True,
                },
                "pipeline": {
                    "type": "string",
                    "required": True,
                    "choices": ["<any>"] + pipeline_choices,
                    "default": "<any>",
                },
                "stage": {
                    "title": "Deal stage",
                    "type": "string",
                    "required": True,
                    "choices": ["<any>"] + stage_choices,
                    "default": "<any>",
                },
                "status": {
                    "title": "Deal status",
                    "type": "string",
                    "required": True,
                    "choices": [
                        {"title": "<any>", "value": "all_not_deleted"},
                        "open",
                        "won",
                        "lost",
                    ],
                    "default": "<any>",
                },
            },
        }

    def can_backfill(self):
        return False

    def _paginated_request(self, url, params, start=0):
        response = self.session.get(url, params={**params, "start": start})
        response.raise_for_status()
        obj = response.json()
        data = obj["data"] or []
        pagination = obj["additional_data"]["pagination"]
        if pagination["more_items_in_collection"]:
            return data + self._paginated_request(
                url, params, start=pagination["next_start"]
            )
        return data

    def collect_latest(self) -> MeasurementTuple:
        # Parameters
        metric = self.config["metric"]
        pipeline = self.config["pipeline"]
        stage = self.config["stage"]
        status = self.config["status"]

        # Documentation:
        # https://developers.pipedrive.com/docs/api/v1/Deals#getDeals
        url = f"{BASE_URL}/deals"
        params = {
            "status": status,
        }
        if stage != "<any>":
            params["stage_id"] = stage
        data = self._paginated_request(url, params)

        def keep_deal(deal):
            if pipeline != "<any>" and deal["pipeline_id"] != int(pipeline):
                return False
            return True

        deals = [d for d in data if keep_deal(d)]

        if metric == "count":
            value = len(deals)
        else:
            raise NotImplementedError(f"Unknown metric {metric}")
        return MeasurementTuple(
            date=date.today(),
            value=value,
        )
