import logging
from typing import TYPE_CHECKING, Dict, Optional, Union

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.urls import reverse
from django_jsonform.models.fields import JSONField

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS, Integration
from integrations.base import EMPTY_CONFIG_SCHEMA, WebAuthIntegration

from .measurement import Measurement
from .organization import Organization

if TYPE_CHECKING:
    from .user import User

import uuid

logger = logging.getLogger(__name__)


class Metric(models.Model):
    id = models.UUIDField(
        auto_created=True,
        primary_key=True,
        serialize=False,
        verbose_name="ID",
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=128)
    integration_id = models.CharField(
        max_length=128, choices=[(k, k) for k in INTEGRATION_IDS]
    )
    integration_credentials = models.JSONField(blank=True, null=True)
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.CASCADE
    )
    dashboards: models.ManyToManyField = models.ManyToManyField(
        "Dashboard", through="dashboard_metrics", blank=True
    )
    higher_is_better = models.BooleanField(
        default=True,
        help_text="Whether or not high values are considered a good outcome",
    )
    enable_medals = models.BooleanField(
        default=False, help_text="Highlight the top 3 values"
    )
    last_collect_attempt = models.DateTimeField(blank=True, null=True)
    target = models.FloatField(blank=True, null=True, help_text="Target value")

    # The credentials can be saved either in db, or in cache, while the object
    # is temporarily being built. We therefore allow this to be changed later.
    def save_integration_credentials(self):
        self.save()

    def callable_config_schema(model_instance: Optional["Metric"] = None) -> Dict:
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
                if (
                    not model_instance.can_web_auth
                    or model_instance.integration_credentials
                ):
                    with model_instance.integration_instance as inst:
                        # Note: the call might crash for some reason.
                        # We don't want to have a fallback here as there
                        # is no way the user can recover from this
                        # (it could be any error!)
                        return inst.callable_config_schema()
            # There's no callable schema
            return instance_class.config_schema
        # No model instance, return empty schema
        return EMPTY_CONFIG_SCHEMA

    integration_config = JSONField(
        blank=True,
        null=True,
        schema=callable_config_schema,
        verbose_name="Integration configuration",
    )
    user = models.ForeignKey("User", on_delete=models.CASCADE, verbose_name="Owner")

    def get_absolute_url(self):
        return reverse("metric-details", args=[self.pk])

    @property
    def last_non_nan_measurement(self) -> Optional["Measurement"]:
        return (
            Measurement.objects.exclude(value=float("nan"))
            .filter(metric=self.pk)
            .order_by("updated_at")
            .last()
        )

    @property
    def can_web_auth(self):
        return issubclass(INTEGRATION_CLASSES[self.integration_id], WebAuthIntegration)

    @property
    def integration_instance(self) -> Integration:
        integration_class = INTEGRATION_CLASSES[self.integration_id]

        def credentials_updater(new_credentials):
            self.integration_credentials = new_credentials
            self.save_integration_credentials()

        return integration_class(
            self.integration_config,
            credentials=self.integration_credentials,
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

    def can_edit(self, user: Union["User", AnonymousUser]) -> bool:
        # Owner or org admin
        if self.user == user:
            return True
        if not self.organization:
            return False
        return self.organization.is_admin(user)

    def can_view(self, user: Union["User", AnonymousUser]) -> bool:
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        if not self.organization:
            return False
        return self.organization.is_member(user)

    def can_delete(self, user: Union["User", AnonymousUser]) -> bool:
        # Owner or org admin
        if self.user == user:
            return True
        if not self.organization:
            return False
        return self.organization.is_admin(user)

    def can_be_backfilled_by(self, user: Union["User", AnonymousUser]) -> bool:
        if not self.can_backfill:
            return False
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        if self.organization:
            return self.organization.is_member(user)
        return False

    def can_transfer_ownership(self, user: Union["User", AnonymousUser]) -> bool:
        if self.user == user:
            return True
        if self.organization and self.organization.is_admin(user):
            return True
        return False

    def can_alter_credentials_by(self, user: Union["User", AnonymousUser]) -> bool:
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        if self.organization:
            return self.organization.is_member(user)
        return False

    def __str__(self):
        return f"{self.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "name"), name="unique_metric")
        ]
