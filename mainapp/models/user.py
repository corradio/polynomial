from typing import TYPE_CHECKING, Optional

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.manager import Manager

from .metric import Metric


class User(AbstractUser):
    # tz, see https://docs.djangoproject.com/en/4.1/topics/i18n/timezones/
    if TYPE_CHECKING:
        emailaddress_set: Manager[EmailAddress]
        socialaccount_set: Manager[SocialAccount]

    last_dashboard_visit = models.DateTimeField(null=True)

    @classmethod
    def get_by_email(cls, email, only_verified=True):
        try:
            extra_filters = {}
            if only_verified:
                extra_filters["verified"] = True
            return (
                EmailAddress.objects.select_related("user")
                .get(
                    email__iexact=email,
                    **extra_filters,
                )
                .user
            )
        except EmailAddress.DoesNotExist:
            raise User.DoesNotExist from None

    @property
    def name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    @property
    def avatar_url(self) -> Optional[str]:
        avatar_urls = [
            acc.get_avatar_url()
            for acc in self.socialaccount_set.all()
            if acc.get_avatar_url()
        ]
        if avatar_urls:
            return avatar_urls[0]
        return None

    def get_viewable_metrics(self) -> models.QuerySet[Metric]:
        return Metric.objects.all().filter(
            Q(user=self) | Q(organization__in=self.organization_set.all())
        )

    def __str__(self):
        return f"{self.name} ({self.email})"
