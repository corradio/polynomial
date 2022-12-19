import json
from datetime import date, timedelta
from typing import Optional

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django_jsonform.models.fields import JSONField

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS, Integration
from integrations.models import EMPTY_CONFIG_SCHEMA


class User(AbstractUser):
    # tz, see https://docs.djangoproject.com/en/4.1/topics/i18n/timezones/
    pass


class Metric(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=128)
    integration_id = models.CharField(
        max_length=128, choices=[(k, k) for k in INTEGRATION_IDS]
    )

    def callable_config_schema(model_instance: Optional["Metric"] = None):
        # See https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        # `model_instance` will be None while creating new object
        if model_instance and model_instance.integration_id:
            return INTEGRATION_CLASSES[model_instance.integration_id].config_schema
        # Empty schema
        return EMPTY_CONFIG_SCHEMA

    integration_config = JSONField(blank=True, null=True, schema=callable_config_schema)

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def get_absolute_url(self):
        return reverse("metric-details", args=[self.pk])

    def get_integration_instance(self) -> Integration:
        integration_class = INTEGRATION_CLASSES[self.integration_id]
        return integration_class(self.integration_config)

    def can_backfill(self):
        return self.get_integration_instance().can_backfill()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "name"), name="unique_metric")
        ]


class Measurement(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    value = models.FloatField()

    metric = models.ForeignKey(Metric, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.date} = {self.value}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("metric", "date"), name="unique_measurement"
            )
        ]
