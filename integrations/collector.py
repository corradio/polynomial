import os
from typing import Dict, Type, TypeVar

from integrations.integration import Integration, Measurement

T = TypeVar("T", bound=Integration)

import importlib
import inspect
import pkgutil

INTEGRATION_CLASSES = {
    integration_name: inspect.getmembers(
        importlib.import_module(f"integrations.implementations.{integration_name}"),
        lambda member: inspect.isclass(member)
        and member != Integration
        and issubclass(member, Integration),
    )[0][
        1
    ]  # First match, second element (which is the class)
    for (_, integration_name, _) in pkgutil.iter_modules(
        ["integrations/implementations"]
    )
}


def collect(integration_name: str) -> int:
    config: Dict = {
        "site_id": "app.electricitymaps.com",
        "metric": "visitors",
        "filters": [],
    }
    secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
    integration_class = INTEGRATION_CLASSES[integration_name]
    inst = integration_class(config, secrets)
    return inst.collect_latest()
