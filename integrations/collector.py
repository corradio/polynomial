import os
from typing import Dict, Type, TypeVar

from . import INTEGRATION_CLASSES
from .models import Integration, MeasurementTuple


def collect(integration_name: str) -> MeasurementTuple:
    config: Dict = {
        "site_id": "app.electricitymaps.com",
        "metric": "visitors",
        "filters": [],
    }
    secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
    integration_class = INTEGRATION_CLASSES[integration_name]
    inst = integration_class(config, secrets)
    return inst.collect_latest()
