from datetime import date, timedelta
from typing import List, NewType, Tuple

Measurement = NewType("Measurement", Tuple[date, int])


class Integration:
    def __init__(self, config, secrets):
        self.config = config
        self.secrets = secrets

    def collect_latest(self) -> Measurement:
        return self.collect_past(date.today() - timedelta(days=1))

    def collect_past(self, date: date) -> Measurement:
        raise NotImplementedError()

    def collect_past_multi(self, dates: List[date]) -> List[Measurement]:
        return [self.collect_past(dt) for dt in dates]

    @classmethod
    def get_config_schema(self):
        """Use https://bhch.github.io/react-json-form/playground"""
        return {}
