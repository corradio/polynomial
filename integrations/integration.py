from abc import ABC, abstractmethod
from typing import List, Tuple, NewType
from datetime import datetime

Measurement = NewType("Measurement", Tuple[datetime, int])


class Integration(ABC):
    def __init__(self, config, secrets):
        self.config = config
        self.secrets = secrets

    def collect_latest(self) -> Measurement:
        return self.collect_past(datetime.now())

    def collect_past(self, datetime: datetime) -> Measurement:
        raise NotImplementedError()

    def collect_past_multi(self, datetimes: List[datetime]) -> List[Measurement]:
        return [self.collect_past(dt) for dt in datetimes]
