import logging
from typing import TYPE_CHECKING, Optional, Union

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import AbstractUser, AnonymousUser
from django.db import models
from django.db.models import Q
from django.db.models.manager import Manager
from django.urls import reverse
from django.utils.text import slugify
from django_jsonform.models.fields import JSONField

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS, Integration
from integrations.base import EMPTY_CONFIG_SCHEMA, WebAuthIntegration

logger = logging.getLogger(__name__)


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


class Metric(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=128)
    integration_id = models.CharField(
        max_length=128, choices=[(k, k) for k in INTEGRATION_IDS]
    )
    integration_credentials = models.JSONField(blank=True, null=True)
    organizations: models.ManyToManyField = models.ManyToManyField(
        "Organization", blank=True
    )
    dashboards: models.ManyToManyField = models.ManyToManyField(
        "Dashboard", through="dashboard_metrics", blank=True
    )
    higher_is_better = models.BooleanField(
        default=True,
        help_text="Whether or not high values are considered a good outcome",
    )
    enable_medals = models.BooleanField(
        default=True, help_text="Highlight the top 3 values"
    )

    # The credentials can be saved either in db, or in cache, while the object
    # is temporarily being built. We therefore allow this to be changed later.
    def save_integration_credentials(self):
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
    user = models.ForeignKey(User, on_delete=models.CASCADE)

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

    def can_edit(self, user: Union[User, AnonymousUser]):
        # Owner or org admin
        if self.user == user:
            return True
        return any(o.is_admin(user) for o in self.organizations.all())

    def can_view(self, user: Union[User, AnonymousUser]):
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        return any(o.is_member(user) for o in self.organizations.all())

    def can_be_backfilled_by(self, user: Union[User, AnonymousUser]) -> bool:
        if not self.can_backfill:
            return False
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        return any(o.is_member(user) for o in self.organizations.all())

    def can_alter_credentials_by(self, user: Union[User, AnonymousUser]) -> bool:
        if self.can_edit(user):
            return True
        # Check if user is *member* of any of the orgs that this
        # metric belong to
        return any(o.is_member(user) for o in self.organizations.all())

    def __str__(self):
        return f"{self.name}"

    def organizations_pk_list(self):
        return [x.pk for x in self.organizations.all()]

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
