from datetime import date, timedelta
from typing import Any, Dict, List, NamedTuple

MeasurementTuple = NamedTuple("MeasurementTuple", [("date", date), ("value", int)])


EMPTY_CONFIG_SCHEMA = {"type": "object", "keys": {}}


class Integration:
    config_schema: Dict = (
        EMPTY_CONFIG_SCHEMA  # Use https://bhch.github.io/react-json-form/playground
    )

    def __init__(self, config: Dict, secrets: Dict):
        self.config = config
        self.secrets = secrets

    def collect_latest(self) -> MeasurementTuple:
        return self.collect_past(date.today() - timedelta(days=1))

    def collect_past(self, date: date) -> MeasurementTuple:
        raise NotImplementedError()

    def collect_past_multi(self, dates: List[date]) -> List[MeasurementTuple]:
        return [self.collect_past(dt) for dt in dates]
