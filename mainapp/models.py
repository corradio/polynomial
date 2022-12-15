from django.db import models
from django_jsonform.models.fields import JSONField


class IntegrationConfig(models.Model):
    from integrations.implementations.plausible import Plausible

    items = JSONField(schema=Plausible.get_config_schema())
    date_created = models.DateTimeField(auto_now_add=True)
