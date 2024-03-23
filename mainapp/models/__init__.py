import logging
from typing import Union

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import Q
from django.db.models.manager import Manager
from django.urls import reverse
from django.utils.text import slugify

# Re-export
from .measurement import Measurement  # noqa
from .metric import Metric  # noqa
from .user import User  # noqa

logger = logging.getLogger(__name__)


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


class OrganizationUser(models.Model):
    is_admin = models.BooleanField(default=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,  # Can be null if user is invited but has no account
    )
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
    )
    # Invitations (optional)
    invitation_key = models.UUIDField(unique=True, editable=False, null=True)
    invitee_email = models.EmailField(null=True)
    inviter = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="inviter", null=True
    )

    class Meta:
        unique_together = ("user", "organization", "invitee_email")

    def __str__(self):
        if self.user:
            return "{0} ({1})".format(
                str(self.user) if self.user.is_active else self.user.email,
                self.organization.name,
            )
        else:
            return f"{self.invitee_email} (invited to {self.organization.name})"

    def delete(self, using=None):
        """
        If the organization user is also the owner, this should not be deleted
        unless it's part of a cascade from the Organization.
        If there is no owner then the deletion should proceed.
        """
        if self.organization.owner.pk == self.pk:
            raise ValueError(
                "Cannot delete organization owner before having transferred ownership"
            )
        super().delete(using=using)

    def get_absolute_url(self):
        if self.user:
            return reverse(
                "organization_user_detail",
                kwargs={
                    "organization_pk": self.organization.pk,
                    "user_pk": self.user.pk,
                },
            )
        else:
            return reverse("invitation_accept", args=[self.invitation_key])

    def is_owner(self):
        if not self.user:
            return False
        return self.organization.is_owner(self.user)


class Organization(models.Model):
    name = models.CharField(max_length=128)
    slug = models.SlugField(unique=True)
    organizationuser_set: Manager[OrganizationUser]
    users = models.ManyToManyField(
        User,
        through=OrganizationUser,
        related_name="organization_users",
        through_fields=("organization", "user"),
    )
    owner = models.ForeignKey(User, on_delete=models.PROTECT)

    # Used for spreadsheet export
    google_spreadsheet_export_credentials = models.JSONField(blank=True, null=True)
    google_spreadsheet_export_spreadsheet_id = models.CharField(
        max_length=128, blank=True, null=True
    )
    google_spreadsheet_export_sheet_name = models.CharField(
        max_length=128, blank=True, null=True
    )
    # Used for slack notifications
    slack_notifications_credentials = models.JSONField(blank=True, null=True)
    slack_notifications_channel = models.CharField(
        max_length=128, blank=True, null=True
    )

    def __str__(self):
        return self.name

    def add_user(self, user, is_admin=False):
        """
        Adds a new user and if the first user makes the user an admin and
        the owner.
        """
        users_count = self.users.all().count()
        if users_count == 0:
            is_admin = True
        org_user = OrganizationUser.objects.create(
            user=user, organization=self, is_admin=is_admin
        )
        if users_count == 0:
            self.owner = user
            self.save()

        return org_user

    def remove_user(self, user: User):
        org_user = OrganizationUser.objects.get(user=user, organization=self)
        org_user.delete()

    def is_admin(self, user: Union[User, AnonymousUser]):
        if isinstance(user, AnonymousUser):
            return False
        return (
            True
            if self.organizationuser_set.filter(user=user, is_admin=True)
            else False
        )

    def is_owner(self, user: Union[User, AnonymousUser]):
        return self.owner == user

    def is_member(self, user: Union[User, AnonymousUser]):
        return True if user in self.users.all() else False


class OrganizationInvitation(OrganizationUser):
    class Meta:
        proxy = True

    def accept(self, user):
        # Update the associated org user
        self.user = user
        return self.save()


class Marker(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    text = models.CharField(max_length=128)

    metric = models.ForeignKey(Metric, on_delete=models.CASCADE)

    def can_edit(self, user: Union[User, AnonymousUser]) -> bool:
        return self.metric.can_edit(user)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("metric", "date"), name="unique_marker")
        ]
