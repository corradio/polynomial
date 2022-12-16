import pkgutil
from datetime import date, timedelta
from typing import List

from django.contrib.auth.models import AbstractUser
from django.db import models
from django_jsonform.models.fields import JSONField

# ** Non-database models


class Integration:
    def __init__(self, config, secrets):
        self.config = config
        self.secrets = secrets

    def collect_latest(self) -> "Measurement":
        return self.collect_past(date.today() - timedelta(days=1))

    def collect_past(self, date: date) -> "Measurement":
        raise NotImplementedError()

    def collect_past_multi(self, dates: List[date]) -> List["Measurement"]:
        return [self.collect_past(dt) for dt in dates]

    @classmethod
    def get_config_schema(self):
        """Use https://bhch.github.io/react-json-form/playground"""
        return {}


INTEGRATION_NAMES = [
    integration_name
    for (_, integration_name, _) in pkgutil.iter_modules(
        ["mainapp/integrations/implementations"]
    )
]


# ** Database models


class User(AbstractUser):
    # tz, see https://docs.djangoproject.com/en/4.1/topics/i18n/timezones/
    pass


class Metric(models.Model):
    name = models.CharField(max_length=128)

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f'Metric("{self.name}")'

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "user_id"), name="unique_name_user_id"
            )
        ]


class IntegrationInstance(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_collected_at = models.DateTimeField(blank=True, null=True)
    name = models.CharField(max_length=128, choices=[(k, k) for k in INTEGRATION_NAMES])
    config = models.JSONField(blank=True, null=True)
    secrets = models.JSONField(blank=True, null=True)  # TODO: Encrypt

    metric = models.OneToOneField(Metric, on_delete=models.CASCADE)


class Measurement(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    value = models.PositiveIntegerField()

    metric = models.ForeignKey(Metric, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.date} = {self.value}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("metric", "date"), name="unique_metric_date"
            )
        ]


# TODO: Remove so it doesn't end up in Database(!)
class IntegrationConfig(models.Model):
    from .integrations.implementations.plausible import Plausible

    items = JSONField(schema=Plausible.get_config_schema())
    date_created = models.DateTimeField(auto_now_add=True)
