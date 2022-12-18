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

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        # Default implementation uses `collect_past` for each date
        dates = [date_end]
        while True:
            new_date = dates[-1] - timedelta(days=1)
            if new_date < date_start:
                break
            else:
                dates.append(new_date)
        return [self.collect_past(dt) for dt in dates]
