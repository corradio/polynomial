from typing import Union

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify

from .metric import Metric
from .organization import Organization
from .user import User


class Dashboard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # A dashboard can have several metrics, and a metric can belong to multiple dashboards
    metrics = models.ManyToManyField(Metric)
    slug = models.SlugField()
    is_public = models.BooleanField(default=False)
    name = models.CharField(max_length=128)
    organization = models.ForeignKey(
        "Organization", null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        username_or_org_slug = (
            self.organization.slug if self.organization else self.user.username
        )
        return reverse(
            "dashboard",
            kwargs={
                "username_or_org_slug": username_or_org_slug,
                "dashboard_slug": self.slug,
            },
        )

    def can_view(self, user: Union[User, AnonymousUser]):
        # To have access, we must either:
        # - dashboard be public
        # - user own dashboard
        # - user be member of dashboard org
        if isinstance(user, AnonymousUser):
            return self.is_public
        if not self.organization:
            return self.user == user
        return user in self.organization.users.all()

    def can_edit(self, user: Union[User, AnonymousUser]):
        if not self.organization:
            return self.user == user
        # Owner can edit
        if self.user == user:
            return True
        # Anyone in the org can edit
        return user in self.organization.users.all()

    def can_delete(self, user: Union[User, AnonymousUser]):
        return self.user == user

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @classmethod
    def get_all_viewable_by(cls, user: Union[User, AnonymousUser]):
        # To have access, we must either:
        # - dashboard be public
        # - user own dashboard
        # - user be member of dashboard org
        if isinstance(user, User):
            # User is logged in
            organizations = Organization.objects.filter(users=user)
            access_query = Q(user=user) | Q(organization__in=organizations)
            # Note: public dashboards that are not of one's org/user
            # are not included here, which differs from `self.can_view`
            return Dashboard.objects.all().filter(access_query)
        # User is anonymous
        return Dashboard.objects.all().filter(is_public=True)

    class Meta:
        # Remember that null values are not considered equals in the constraint
        # meaning it will ignore the tuple if one field is NULL
        # See https://www.postgresql.org/docs/13/ddl-constraints.html#DDL-CONSTRAINTS-UNIQUE-CONSTRAINTS
        constraints = [
            # (org, slug) needs to be unique (will ignore if org or slug is NULL)
            models.UniqueConstraint(
                fields=("organization", "slug"), name="unique_dashboard_org_slug"
            ),
            # (user, slug) needs to be unique only when no org
            # (will ignore if slug is NULL)
            models.UniqueConstraint(
                fields=("user", "slug"),
                name="unique_dashboard_owner_slug",
                condition=models.Q(organization__isnull=True),
            ),
        ]
