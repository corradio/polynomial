import time
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, final

import requests

from ..base import MeasurementTuple, OAuth2Integration, UserFixableError
from ..utils import batch_range_by_max_batch, get_secret

ELEMENTS_PER_CALL = 10000
LINKEDIN_VERSION_HEADER = "202408"

METRICS: List[Dict[str, Any]] = [
    # Share statistics
    # See https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/organizations/share-statistics?view=li-lms-2022-12&tabs=http#share-statistics-data-schema
    {
        "title": "Post impressions (unique)",
        "value": "uniqueImpressionsCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post impressions (total)",
        "value": "impressionCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post shares",
        "value": "shareCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post engagement",
        "value": "engagement",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post clicks",
        "value": "clickCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post likes",
        "value": "likeCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
    {
        "title": "Post comments",
        "value": "commentCount",
        "endpoint": "organizationalEntityShareStatistics",
    },
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

    description = "Followers, shares and mentions of your LinkedIn page and content."

    def callable_config_schema(self):
        request_params = {
            "projection": "(elements*(*,organization~(localizedName)))",
            "q": "roleAssignee",
            "role": "ADMINISTRATOR",
            "state": "APPROVED",
        }
        response = self.session.get(
            "https://api.linkedin.com/v2/organizationAcls", params=request_params
        )
        if response.status_code == 401:
            # Could e.g. be
            # {"status":401,"serviceErrorCode":65601,"code":"REVOKED_ACCESS_TOKEN","message":"The token used in the request has been revoked by the user"}
            org_choices = []
        else:
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
                    "title": "Organization",
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
            },
        }

    def _get_metric_config_for_key(self, metric_key):
        metric_key = self.config["metric"]
        metric_matches = [m for m in METRICS if m["value"] == metric_key]
        if not metric_matches:
            raise UserFixableError(
                f"Metric {metric_key} is invalid. Please pick another one."
            )
        return metric_matches[0]

    def can_backfill(self):
        metric_config = self._get_metric_config_for_key(self.config["metric"])
        return metric_config.get("can_backfill", True)

    def __enter__(self):
        super().__enter__()
        self.session.headers = {
            "LinkedIn-Version": "202312",
        }
        return self

    def _paginated_query(self, url, request_params, start=0) -> Iterable[Dict]:
        queries = 0
        while True:
            # Make request
            r = self.session.get(
                url,
                headers={"LinkedIn-Version": LINKEDIN_VERSION_HEADER},
                params={**request_params, "start": start, "count": ELEMENTS_PER_CALL},
            )
            try:
                r.raise_for_status()
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in [400, 403]:
                    raise requests.HTTPError(
                        str(e) + f'\n{e.response.json()["message"]}',
                        response=e.response,
                    ) from None
                else:
                    raise
            data = r.json()
            elements = data["elements"]
            # This is the number of items requested
            count = data["paging"]["count"]
            assert (
                len(elements) <= count
            ), "More elements returned than requested. Does this API support pagination?"
            # Request done
            queries += 1
            for element in elements:
                yield element
            # You have reached the end of the dataset when your response contains fewer
            # elements in the entities block of the response than your count parameter request.
            if len(elements) < count:
                # Done
                return
            if queries > 10:
                raise Exception(f"Too many interations")
            # Prepare next iteration
            start += count

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> Iterable[MeasurementTuple]:
        # Parameters
        org_id = self.config["org_id"]
        metric = self.config["metric"]
        metric_config = self._get_metric_config_for_key(metric)
        url = f"https://api.linkedin.com/rest/{metric_config['endpoint']}"

        time_start = int(time.mktime(date_start.timetuple()) * 1000)
        time_end = int(time.mktime((date_end + timedelta(days=1)).timetuple()) * 1000)

        # Start time and end time must be less than 14 months apart.
        if (date_end - date_start).days > 365:
            return batch_range_by_max_batch(
                date_start=date_start,
                date_end=date_end,
                max_days=365,
                callable=self.collect_past_range,
            )

        request_params = {
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
            "timeIntervals.timeGranularityType": "DAY",
            "timeIntervals.timeRange.start": time_start,
            "timeIntervals.timeRange.end": time_end,
        }

        elements = self._paginated_query(url, request_params)

        # By default we assume we're dealing with totalShareStatistics
        value_getter = metric_config.get(
            "value_getter", lambda element: element["totalShareStatistics"][metric]
        )

        return (
            MeasurementTuple(
                date=date.fromtimestamp(e["timeRange"]["start"] / 1000),
                value=float(value_getter(e)),
            )
            for e in elements
        )

    def collect_latest(self) -> MeasurementTuple:
        if self.can_backfill():
            # LinkedIn API sometimes returns delayed results
            # We therefore here call collect_past_range and
            # seek results in the past
            max_delay = 7
            results = list(
                self.collect_past_range(
                    date_start=date.today() - timedelta(days=max_delay),
                    date_end=date.today() - timedelta(days=1),
                )
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
                f"https://api.linkedin.com/rest/networkSizes/urn:li:organization:{org_id}?edgeType=COMPANY_FOLLOWED_BY_MEMBER",
                headers={"LinkedIn-Version": LINKEDIN_VERSION_HEADER},
            )
            response.raise_for_status()
            data = response.json()
            return MeasurementTuple(date=date.today(), value=data["firstDegreeSize"])

        # Other cases
        url = f"https://api.linkedin.com/v2/{metric_config['endpoint']}"

        request_params = {
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
            "count": ELEMENTS_PER_CALL,
        }

        elements = list(self._paginated_query(url, request_params))
        value_getter = metric_config["value_getter"]
        value = float(value_getter(elements[0]))

        return MeasurementTuple(date=date.today(), value=value)
