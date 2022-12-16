from datetime import date, timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django_jsonform.models.fields import JSONField

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.models import EMPTY_CONFIG_SCHEMA


class User(AbstractUser):
    # tz, see https://docs.djangoproject.com/en/4.1/topics/i18n/timezones/
    pass


class IntegrationInstance(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_collected_at = models.DateTimeField(blank=True, null=True)
    integration_id = models.CharField(
        max_length=128, choices=[(k, k) for k in INTEGRATION_IDS]
    )
    metric_name = models.CharField(max_length=128)
    secrets = models.JSONField(blank=True, null=True)  # TODO: Encrypt

    def callable_config_schema(model_instance=None):
        # See https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        # `model_instance` will be None while creating new object
        if model_instance and model_instance.pk:
            return INTEGRATION_CLASSES[model_instance.integration_id].config_schema
        # Empty schema
        return EMPTY_CONFIG_SCHEMA

    config = JSONField(blank=True, null=True, schema=callable_config_schema)

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "metric_name"), name="unique_integration_instance"
            )
        ]


class Measurement(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    value = models.FloatField()
    metric_name = models.CharField(max_length=128)

    integration_instance = models.ForeignKey(
        IntegrationInstance, on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"{self.date} = {self.value}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("integration_instance", "date"), name="unique_measurement"
            )
        ]
