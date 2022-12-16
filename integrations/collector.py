from typing import Dict

from . import INTEGRATION_CLASSES
from .models import Integration, MeasurementTuple


def collect(integration_id: str, config: Dict, secrets: Dict) -> MeasurementTuple:
    integration_class = INTEGRATION_CLASSES[integration_id]
    inst = integration_class(config, secrets)
    return inst.collect_latest()
