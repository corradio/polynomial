import time
from datetime import date, timedelta
from typing import Any, Dict, List, final

import requests

from ..base import MeasurementTuple, OAuth2Integration
from ..utils import get_secret

ELEMENTS_PER_CALL = 100

METRICS: List[Dict[str, Any]] = [
    # Share statistics
    # See https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/organizations/share-statistics?view=li-lms-2022-12&tabs=http#share-statistics-data-schema
    {
        "title": "Content impressions (unique)",
        "value": "uniqueImpressionsCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content impressions (total)",
        "value": "impressionCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content shares",
        "value": "shareCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content engagement",
        "value": "engagement",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content clicks",
        "value": "clickCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content likes",
        "value": "likeCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Content comments",
        "value": "commentCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    # These are only lifetime statistics
    # "shareMentionsCount", # This one can't be backfilled
    # "commentMentionsCount", # This one can't be backfilled
    # Follower statistics
    # See https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/organizations/follower-statistics?view=li-lms-2022-12&tabs=http
    {
        "title": "Followers (new)",
        "value": "followerGains",
        "endpoint": "organizationalEntityFollowerStatistics",
        "value_getter": lambda element: element["followerGains"]["organicFollowerGain"],
    },
    # These are lifetime statistics
    {"title": "Followers (total)", "value": "followerCount", "can_backfill": False},
]


@final
class LinkedIn(OAuth2Integration):
    client_id = get_secret("LINKEDIN_CLIENT_ID")
    client_secret = get_secret("LINKEDIN_CLIENT_SECRET")
    authorization_url = "https://www.linkedin.com/oauth/v2/authorization"
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    refresh_url = "https://www.linkedin.com/oauth/v2/accessToken"
    scopes = ["r_organization_admin"]
    token_extras = {"include_client_id": True}

    def callable_config_schema(self):
        request_params = {
            "projection": "(elements*(*,organization~(localizedName)))",
            "q": "roleAssignee",
            "role": "ADMINISTRATOR",
            "state": "APPROVED",
        }
        response = self.session.get(
            "https://api.linkedin.com/rest/organizationAcls", params=request_params
        )
        response.raise_for_status()
        org_choices = sorted(
            [
                {
                    "title": f'{e["organization~"]["localizedName"]} ({e["organization"].split(":")[-1]})',
                    "value": e["organization"].split(":")[-1],
                }
                for e in response.json()["elements"]
            ],
            key=lambda d: d["title"],
        )

        # Use https://bhch.github.io/react-json-form/playground
        return {
            "type": "dict",
            "keys": {
                "org_id": {
                    "type": "string",
                    "required": True,
                    "choices": org_choices,
                },
                "metric": {
                    "type": "string",
                    "choices": sorted(
                        [{"title": m["title"], "value": m["value"]} for m in METRICS],
                        key=lambda d: d["title"],
                    ),
                    "default": "likeCount",
                    "required": True,
                    "helpText": "Note: sponsored activity is ignored from these statistics.",
                },
                "filters": {"type": "array", "items": {"type": "string"}},
            },
        }

    def _get_metric_config_for_key(self, metric_key):
        metric_key = self.config["metric"]
        metric_matches = [m for m in METRICS if m["value"] == metric_key]
        assert metric_matches, f"Couldn't find metric {metric_key}"
        return metric_matches[0]

    def can_backfill(self):
        metric_config = self._get_metric_config_for_key(self.config["metric"])
        return metric_config.get("can_backfill", True)

    def __enter__(self):
        super().__enter__()
        self.session.headers = {
            "LinkedIn-Version": "202212",
        }
        return self

    def _paginated_query(self, url, request_params, start=0) -> List[Dict]:
        if start:
            request_params = {**request_params, "start": start}

        r = self.session.get(
            url,
            params=request_params,
        )

        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code in [400, 403]:
                raise requests.HTTPError(
                    str(e) + f'\n{e.response.json()["message"]}'
                ) from None
            else:
                raise
        data = r.json()

        # Paging
        count = data["paging"]["count"]
        # Total is sometimes missing from the response
        total = data["paging"].get("total")
        if len(data["elements"]) < count:
            return data["elements"]
        else:
            all_elements = data["elements"] + self._paginated_query(
                url, request_params, start=start + count
            )
            if total is not None:
                assert len(all_elements) == total
            return all_elements

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Parameters
        org_id = self.config["org_id"]
        metric = self.config["metric"]
        metric_config = self._get_metric_config_for_key(metric)
        url = f"https://api.linkedin.com/rest/{metric_config['endpoint']}"

        time_start = int(time.mktime(date_start.timetuple()) * 1000)
        time_end = int(time.mktime((date_end + timedelta(days=1)).timetuple()) * 1000)

        request_params = {
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
            "timeIntervals.timeGranularityType": "DAY",
            "timeIntervals.timeRange.start": time_start,
            "timeIntervals.timeRange.end": time_end,
            "count": ELEMENTS_PER_CALL,
        }

        elements = self._paginated_query(url, request_params)

        # By default we assume we're dealing with totalShareStatistics
        value_getter = metric_config.get(
            "value_getter", lambda element: element["totalShareStatistics"][metric]
        )

        return [
            MeasurementTuple(
                date=date.fromtimestamp(e["timeRange"]["start"] / 1000),
                value=float(value_getter(e)),
            )
            for e in elements
        ]

    def collect_latest(self) -> MeasurementTuple:
        if self.can_backfill():
            # LinkedIn API sometimes returns delayed results
            # We therefore here call collect_past_range and
            # seek results in the past
            max_delay = 7
            results = self.collect_past_range(
                date_start=date.today() - timedelta(days=max_delay),
                date_end=date.today() - timedelta(days=1),
            )
            return results[-1]

        # This metric can't backfill
        metric_key = self.config["metric"]
        metric_config = self._get_metric_config_for_key(metric_key)
        org_id = self.config["org_id"]

        if metric_key == "followerCount":
            # This metric requires a particular endpoint.
            # We hardcode it here.
            response = self.session.get(
                f"https://api.linkedin.com/rest/networkSizes/urn:li:organization:{org_id}?edgeType=CompanyFollowedByMember"
            )
            response.raise_for_status()
            data = response.json()
            return MeasurementTuple(date=date.today(), value=data["firstDegreeSize"])

        # Other cases
        value_getter = metric_config["value_getter"]
        url = f"https://api.linkedin.com/rest/{metric_config['endpoint']}"

        request_params = {
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
            "count": ELEMENTS_PER_CALL,
        }

        elements = self._paginated_query(url, request_params)
        value = float(value_getter(elements))

        return MeasurementTuple(date=date.today(), value=value)
