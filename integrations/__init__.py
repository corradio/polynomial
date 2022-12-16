import importlib
import inspect
import pkgutil

from .models import Integration

INTEGRATION_IDS = [
    integration_name
    for (_, integration_name, _) in pkgutil.iter_modules(
        ["integrations/implementations"]
    )
]

INTEGRATION_CLASSES = {
    integration_name: inspect.getmembers(
        importlib.import_module(f"integrations.implementations.{integration_name}"),
        lambda member: inspect.isclass(member)
        and member != Integration
        and issubclass(member, Integration),
    )[0][
        1
    ]  # First match, second element (which is the class)
    for integration_name in INTEGRATION_IDS
}
