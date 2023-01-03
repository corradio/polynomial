from abc import abstractmethod
from datetime import date, timedelta
from typing import Any, Callable, ClassVar, Dict, List, NamedTuple, Optional

import requests
from oauthlib.oauth2 import WebApplicationClient

MeasurementTuple = NamedTuple("MeasurementTuple", [("date", date), ("value", int)])


EMPTY_CONFIG_SCHEMA = {"type": "object", "keys": {}}


class Integration:
    config_schema: Dict = (
        EMPTY_CONFIG_SCHEMA  # Use https://bhch.github.io/react-json-form/playground
    )

    def __init__(self, config: Dict, *args, **kwargs):
        self.config = config

    def __enter__(self):
        # Database connections can be done here
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup should be done here (e.g. database connection cleanup)
        pass

    @abstractmethod
    def can_backfill(self) -> bool:
        pass

    def earliest_backfill(self) -> date:
        return date.min

    def collect_latest(self) -> MeasurementTuple:
        # Default implementation uses `collect_past`,
        # and thus assumes integration can backfill
        if not self.can_backfill():
            raise NotImplementedError(
                "Integration can't backfill: `collect_latest` should be overridden"
            )
        return self.collect_past(date.today() - timedelta(days=1))

    def collect_past(self, date: date) -> MeasurementTuple:
        raise NotImplementedError()

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Default implementation uses `collect_past` for each date,
        # and thus assumes integration can backfill
        assert self.can_backfill()
        dates = [date_end]
        while True:
            new_date = dates[-1] - timedelta(days=1)
            if new_date < date_start:
                break
            else:
                dates.append(new_date)
        return [self.collect_past(dt) for dt in dates]


class WebAuthIntegration(Integration):
    @classmethod
    @abstractmethod
    def get_authorization_uri(cls, state: str, authorize_callback_uri: str) -> str:
        pass

    @classmethod
    @abstractmethod
    def process_callback(
        cls, uri: str, state: str, authorize_callback_uri: str
    ) -> Dict:
        pass


class OAuth2Integration(WebAuthIntegration):
    # Declare some required attribute
    # TODO: How do we make sure mypy understand that this attribute need
    # to be set in concrete (final) class implementation?
    scopes: ClassVar[List[str]]
    client_id: ClassVar[str]
    client_secret: ClassVar[str]
    authorization_url: ClassVar[str]
    token_url: ClassVar[str]

    def __init__(self, config: Dict, credentials: Dict):
        super().__init__(config)
        self.credentials = credentials

    def __enter__(self):
        assert self.credentials is not None, "Credentials need to be supplied"
        token = self.credentials["access_token"]
        self.r = requests.Session()
        self.r.headers.update({"Authorization": f"token {token}"})
        # Clean up credentials as they shouldn't be used
        del self.credentials
        return self

    @classmethod
    def get_authorization_uri(cls, state: str, authorize_callback_uri: str):
        client = WebApplicationClient(cls.client_id)
        # Prepare authorization request
        print(cls.scopes)
        uri = client.prepare_request_uri(
            cls.authorization_url,
            redirect_uri=authorize_callback_uri,
            scope=cls.scopes,
            state=state,
        )
        return uri

    @classmethod
    def process_callback(cls, uri: str, state: str, authorize_callback_uri: str):
        client = WebApplicationClient(cls.client_id)
        # Checks that the state is valid, will raise
        # MismatchingStateError if not.
        code = client.parse_request_uri_response(uri, state)["code"]
        # Prepare access token request
        data = client.prepare_request_body(
            code=code,
            redirect_uri=authorize_callback_uri,
            client_id=cls.client_id,
            client_secret=cls.client_secret,
        )
        response = requests.post(cls.token_url, data=data)
        client.parse_request_body_response(response.text)
        credentials = client.token
        return credentials
