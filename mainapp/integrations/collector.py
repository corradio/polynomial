import importlib
import inspect
import os
from typing import Dict, Type, TypeVar

from ..models import INTEGRATION_NAMES, Integration, Measurement

INTEGRATION_CLASSES = {
    integration_name: inspect.getmembers(
        importlib.import_module(
            f"mainapp.integrations.implementations.{integration_name}"
        ),
        lambda member: inspect.isclass(member)
        and member != Integration
        and issubclass(member, Integration),
    )[0][
        1
    ]  # First match, second element (which is the class)
    for integration_name in INTEGRATION_NAMES
}


def collect(integration_name: str, save=False) -> Measurement:
    config: Dict = {
        "site_id": "app.electricitymaps.com",
        "metric": "visitors",
        "filters": [],
    }
    secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
    integration_class = INTEGRATION_CLASSES[integration_name]
    inst = integration_class(config, secrets)
    measurement = inst.collect_latest()
    if save:
        measurement.save()
    return measurement
