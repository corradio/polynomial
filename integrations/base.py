import base64
import hashlib
import os
import re
from abc import abstractmethod
from datetime import date, timedelta
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    NamedTuple,
    Optional,
    Tuple,
)

import requests
from requests_oauthlib import OAuth2Session

MeasurementTuple = NamedTuple("MeasurementTuple", [("date", date), ("value", float)])


EMPTY_CONFIG_SCHEMA = {"type": "object", "keys": {}}


class Integration:
    # Use https://bhch.github.io/react-json-form/playground
    config_schema: ClassVar[Dict] = EMPTY_CONFIG_SCHEMA

    def __init__(self, config: Optional[Dict], *args, **kwargs):
        self.config = config or {}

    def __enter__(self):
        # Database connections can be done here
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup should be done here (e.g. database connection cleanup)
        pass

    # This will only be used if the method is overridden
    def callable_config_schema(self) -> Dict:
        return self.config_schema

    @abstractmethod
    def can_backfill(self) -> bool:
        pass

    def earliest_backfill(self) -> date:
        return date.min

    def collect_latest(self) -> MeasurementTuple:
        # Default implementation uses `collect_past` through `collect_past_range`,
        # and thus assumes integration can backfill
        if not self.can_backfill():
            raise NotImplementedError(
                "Integration can't backfill: `collect_latest` should be overridden"
            )
        day = date.today() - timedelta(days=1)
        results = self.collect_past_range(date_start=day, date_end=day)
        if not results:
            raise Exception("No results returned")
        assert len(results) == 1, "More than one result was returned"
        return results[0]

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
    def __init__(
        self,
        config: Optional[Dict],
        credentials: Dict,
        credentials_updater: Callable[[Dict], None],
    ):
        super().__init__(config)
        credentials = credentials
        credentials_updater = credentials_updater
        assert credentials is not None, "Credentials need to be supplied"
        assert (
            credentials_updater is not None
        ), "Credential updated needs to be supplied"

    @classmethod
    @abstractmethod
    def get_authorization_uri_and_code_verifier(
        cls, state: str, authorize_callback_uri: str
    ) -> Tuple[str, Optional[str]]:
        pass

    @classmethod
    @abstractmethod
    def process_callback(
        cls,
        uri: str,
        state: str,
        authorize_callback_uri: str,
        code_verifier: Optional[str] = None,
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
    refresh_url: ClassVar[Optional[str]] = None
    code_challenge_method: ClassVar[Optional[Literal["S256"]]] = None
    authorize_extras: ClassVar[Dict] = {}
    token_extras: ClassVar[Dict] = {}

    session: OAuth2Session

    def __init__(
        self,
        config: Optional[Dict],
        credentials: Dict,
        credentials_updater: Callable[[Dict], None],
    ):
        super().__init__(config, credentials, credentials_updater)
        self.session = OAuth2Session(
            self.client_id,
            scope=self.scopes,
            token=credentials,
            auto_refresh_url=self.refresh_url,
            # If the token gets refreshed, we will have to save it
            token_updater=credentials_updater,
            # For Google, the client_id+secret must be supplied for refresh tokens
            auto_refresh_kwargs={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )

    def __enter__(self):
        assert self.session.authorized
        return self

    @property
    def is_authorized(self) -> bool:
        return self.session.authorized

    @classmethod
    def get_authorization_uri_and_code_verifier(
        cls, state: str, authorize_callback_uri: str
    ) -> Tuple[str, Optional[str]]:
        client = OAuth2Session(
            cls.client_id, scope=cls.scopes, redirect_uri=authorize_callback_uri
        )
        code_challenge = None
        code_verifier = None
        if cls.code_challenge_method is not None:
            code_verifier = base64.urlsafe_b64encode(os.urandom(30)).decode("utf-8")
            code_verifier = re.sub("[^a-zA-Z0-9]+", "", code_verifier)

            code_challenge_b = hashlib.sha256(code_verifier.encode("utf-8")).digest()
            code_challenge = base64.urlsafe_b64encode(code_challenge_b).decode("utf-8")
            code_challenge = code_challenge.replace("=", "")
        # Prepare authorization request
        uri, state = client.authorization_url(
            cls.authorization_url,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=cls.code_challenge_method,
            **cls.authorize_extras,
        )
        return uri, code_verifier

    @classmethod
    def process_callback(
        cls,
        uri: str,
        state: str,
        authorize_callback_uri: str,
        code_verifier: Optional[str] = None,
    ):
        client = OAuth2Session(cls.client_id, redirect_uri=authorize_callback_uri)
        # Checks that the state is valid, will raise
        # MismatchingStateError if not.
        client.fetch_token(
            cls.token_url,
            client_secret=cls.client_secret,
            authorization_response=uri,
            state=state,
            code_verifier=code_verifier,
            **cls.token_extras,
        )
        credentials = client.token
        return credentials
