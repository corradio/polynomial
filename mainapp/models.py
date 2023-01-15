import json
import logging
from datetime import date, timedelta
from typing import Optional

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django_jsonform.models.fields import JSONField

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS, Integration
from integrations.base import EMPTY_CONFIG_SCHEMA, WebAuthIntegration

logger = logging.getLogger(__name__)


class User(AbstractUser):
    # tz, see https://docs.djangoproject.com/en/4.1/topics/i18n/timezones/
    pass


class Metric(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=128)
    integration_id = models.CharField(
        max_length=128, choices=[(k, k) for k in INTEGRATION_IDS]
    )
    credentials = models.JSONField(blank=True, null=True)

    # The credentials can be saved either in db, or in cache, while the object
    # is temporarily being built. We therefore allow this to be changed later.
    def save_credentials(self):
        self.save()

    def callable_config_schema(model_instance: Optional["Metric"] = None):
        # See https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        # `model_instance` will be None while creating new object
        if model_instance and model_instance.integration_id:
            # Check if a callable schema exists
            instance_class = INTEGRATION_CLASSES[model_instance.integration_id]
            if (
                instance_class.callable_config_schema.__qualname__.split(".")[0]
                == instance_class.__name__
            ):
                # We will here attempt to __init__ and __enter__ an
                # integration. This can cause it to crash if it e.g. hasn't
                # been authenticated yet
                # if class is instance of OAuth2Integration, then we will
                # require credentials to __init__
                if not model_instance.can_web_auth or model_instance.credentials:
                    with model_instance.integration_instance as inst:
                        return inst.callable_config_schema()
            # There's no callable schema
            return instance_class.config_schema
        # No model instance, return empty schema
        return EMPTY_CONFIG_SCHEMA

    integration_config = JSONField(blank=True, null=True, schema=callable_config_schema)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def get_absolute_url(self):
        return reverse("metric-details", args=[self.pk])

    @property
    def can_web_auth(self):
        return issubclass(INTEGRATION_CLASSES[self.integration_id], WebAuthIntegration)

    @property
    def integration_instance(self) -> Integration:
        integration_class = INTEGRATION_CLASSES[self.integration_id]

        def credentials_updater(new_credentials):
            self.credentials = new_credentials
            self.save_credentials()

        return integration_class(
            self.integration_config,
            credentials=self.credentials,
            credentials_updater=credentials_updater,
        )

    @property
    def can_backfill(self):
        # This can crash depending on how the integration is implemented
        try:
            return self.integration_instance.can_backfill()
        except:
            logger.exception("Exception while calling `can_backfill`")
            return False

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
