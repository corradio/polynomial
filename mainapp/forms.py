import csv
import uuid
from datetime import date, datetime
from io import TextIOWrapper
from typing import IO, List

from allauth.account.adapter import get_adapter
from django import forms
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from mainapp.models import (
    Dashboard,
    Measurement,
    Metric,
    Organization,
    OrganizationInvitation,
    OrganizationUser,
    User,
)


class MetricForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        # manually set the current instance on the widget
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        self.fields["integration_config"].widget.instance = self.instance

        organizations_field = self.fields["organizations"]
        assert isinstance(organizations_field, forms.ModelChoiceField)
        organizations = Organization.objects.filter(users=user)
        organizations_field.queryset = Organization.objects.filter(users=user)
        organizations_field.help_text = "Sharing a metric with an organization will make it usable by all its members"

        if "dashboards" in self.fields:
            dashboards_field = self.fields["dashboards"]
            assert isinstance(dashboards_field, forms.ModelChoiceField)
            dashboards_field.queryset = Dashboard.objects.all().filter(
                Q(user=user) | Q(organization__in=organizations)
            )
            dashboards_field.help_text = (
                "Adding a metric to a dashboard will also add it to its organization"
            )

    def save(self, *args, **kwargs):
        metric = super().save(*args, **kwargs)
        # Also make sure that for each dashboard,
        # the metric is moved to its organization if applicable
        # to keep ACL consistent
        for dashboard in metric.dashboards.all():
            if dashboard.organization:
                metric.organizations.add(dashboard.organization)
        return metric

    class Meta:
        model = Metric
        fields = [
            "name",
            "organizations",
            "integration_config",
            "integration_id",
        ]

        widgets = {
            # Make this field available to the form but invisible to user
            "integration_id": forms.HiddenInput(),
            "dashboards": forms.CheckboxSelectMultiple(),
            "organizations": forms.CheckboxSelectMultiple(),
        }


class MetricImportForm(forms.ModelForm):
    file = forms.FileField(validators=[FileExtensionValidator(["csv"])])
    date_field = forms.CharField(required=True, initial="datetime")
    value_field = forms.CharField(required=True, initial="value")

    def save(self, commit=True):
        date_field = self.data["date_field"]
        value_field = self.data["value_field"]

        f = self.files["file"]
        reader = csv.DictReader(TextIOWrapper(f))  # type: ignore[arg-type]
        assert reader.fieldnames is not None
        for key in [date_field, value_field]:
            if key not in reader.fieldnames:
                raise forms.ValidationError(f"CSV file is missing '{key}' column")

        metric = self.instance
        num_rows = 0

        def parse_date(s: str) -> date:
            try:
                d = datetime.fromisoformat(s)
            except ValueError as e:
                # Try another method
                try:
                    d = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                except:
                    # Try another method
                    try:
                        d = datetime.strptime(s, "%m/%d/%Y %H:%M:%S")
                    except ValueError as e:
                        raise forms.ValidationError(
                            f"Error while parsing date: '{e}'"
                        ) from None
            return d.date()

        with transaction.atomic():
            for row in reader:
                Measurement.objects.update_or_create(
                    metric=metric,
                    date=parse_date(row[date_field]),
                    defaults={
                        "value": float(row[value_field]),
                    },
                )
                num_rows += 1

        # Start transaction and insert into db
        self.cleaned_data["num_rows"] = num_rows

    class Meta:
        model = Metric
        fields: List[str] = []


class OrganizationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.google_spreadsheet_export_credentials:
            self.fields[
                "google_spreadsheet_export_spreadsheet_id"
            ].widget = forms.HiddenInput()
            self.fields[
                "google_spreadsheet_export_sheet_name"
            ].widget = forms.HiddenInput()

    def save(self, commit=True):
        if not self.instance.pk:
            # This is a CreateForm
            owner = self.cleaned_data["owner"]
            # Create the organization
            org = Organization.objects.create(**self.cleaned_data)
            # Create the owner
            OrganizationUser.objects.create(user=owner, organization=org, is_admin=True)
            # Make sure the owner is part of the members
            assert owner in org.users.all()
            return org
        else:
            return super().save(commit)

    class Meta:
        model = Organization
        fields = [
            "name",
            "owner",
            "slug",
            "google_spreadsheet_export_spreadsheet_id",
            "google_spreadsheet_export_sheet_name",
        ]

        widgets = {
            # Make this field available to the form but invisible to user
            "owner": forms.HiddenInput(),
        }


class OrganizationUserCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        self.organization_pk = kwargs.pop("organization_pk")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        invitee_email = self.cleaned_data["invitee_email"]
        # Check if user is already member of organization
        try:
            invitee = User.get_by_email(invitee_email, only_verified=False)
            try:
                org_user = OrganizationUser.objects.get(
                    user=invitee, organization_id=self.organization_pk
                )
                raise forms.ValidationError("User is already part of organization")
            except OrganizationUser.DoesNotExist:
                pass
        except User.DoesNotExist:
            pass

        # Check if user has already been invited
        try:
            invitation = OrganizationInvitation.objects.get(
                invitee_email=invitee_email,
                organization_id=self.organization_pk,
                user=None,
            )
            raise forms.ValidationError("User is already invited")
        except OrganizationInvitation.DoesNotExist:
            pass
        return cleaned_data

    def save(self, *args, **kwargs):
        invitee_email = self.cleaned_data["invitee_email"]
        try:
            invitee = User.get_by_email(invitee_email, only_verified=False)
        except User.DoesNotExist:
            # User does not exist, will have to be created when signing up
            invitee = None
        invitation = OrganizationInvitation.objects.create(
            user=invitee,  # in case user already exists
            invitation_key=uuid.uuid4(),
            invitee_email=invitee_email,
            inviter=self.request.user,
            # configuration
            is_admin=self.cleaned_data["is_admin"],
            organization_id=self.organization_pk,
        )

        # Send invitation
        invite_url = self.request.build_absolute_uri(
            reverse("invitation_accept", args=[invitation.invitation_key])
        )
        ctx = {
            "invitation": invitation,
            "invite_url": invite_url,
        }
        email_template = "mainapp/email/organizationinvitation_invite"
        get_adapter().send_mail(email_template, invitee_email, ctx)

        return invitation

    class Meta:
        model = OrganizationUser
        exclude = ("user", "organization")
        widgets = {
            # Make this field available to the form but invisible to user
            "inviter": forms.HiddenInput(),
        }
        labels = {"invitee_email": "Email"}


class DashboardForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        user = request.user
        organizations = Organization.objects.filter(users=user)
        organization_field = self.fields["organization"]
        assert isinstance(organization_field, forms.ModelChoiceField)
        organization_field.queryset = Organization.objects.filter(users=user)
        organization_field.help_text = "Dashboard and associated metrics will be made accessible to all organization members"

    def save(self, *args, **kwargs):
        dashboard = super().save(*args, **kwargs)
        # Also make sure that every metric of this dashboard is moved
        # to the organization to keep ACL consistent
        if dashboard.organization:
            for metric in dashboard.metrics.all():
                metric.organizations.add(dashboard.organization)
        return dashboard

    class Meta:
        model = Dashboard
        fields = ["name", "slug", "is_public", "user", "organization"]

        widgets = {
            # Make this field available to the form but invisible to user
            "user": forms.HiddenInput(),
        }


class DashboardMetricAddForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        organizations = Organization.objects.filter(users=user)
        available_metrics = (
            Metric.objects.all()
            .filter(Q(user=user) | Q(organizations__in=organizations))
            .order_by("name")
        )
        metrics_field = self.fields["metrics"]
        assert isinstance(metrics_field, forms.ModelChoiceField)
        metrics_field.queryset = available_metrics
        if self.instance.organization:
            metrics_field.help_text = f"Note: metrics selected will automatically be added to the {self.instance.organization} organization"

    def save(self, *args, **kwargs):
        dashboard = super().save(*args, **kwargs)
        # Also make sure that every metric is moved to organization
        # to keep ACL consistent
        if dashboard.organization:
            for metric in dashboard.metrics.all():
                metric.organizations.add(dashboard.organization)
        return dashboard

    class Meta:
        model = Dashboard
        fields = ["metrics"]
        widgets = {
            "metrics": forms.CheckboxSelectMultiple(),
        }


class MetricIntegrationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        if "request" in kwargs:
            self.request = kwargs.pop("request")
        if "state" in kwargs:
            self.state = kwargs.pop("state")
        super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        if self.has_changed():
            # Reset other fields as well
            if self.instance.pk:
                # Update
                self.instance.integration_credentials = None
                self.instance.integration_config = None
                return super().save(*args, **kwargs)
            else:
                # Creating metric, i.e. use the cache
                metric_cache = self.request.session[self.state]["metric"]
                metric_cache["integration_credentials"] = None
                metric_cache["integration_config"] = None
                metric_cache["integration_id"] = self.cleaned_data["integration_id"]
                self.request.session.modified = True

    class Meta:
        model = Metric
        fields = ["integration_id"]


class MetricDashboardAddForm(forms.ModelForm):
    dashboard_new = forms.CharField(required=False, label="Or create a new dashboard")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        organizations = Organization.objects.filter(users=self.user)
        if "dashboards" in self.fields:
            dashboards_field = self.fields["dashboards"]
            assert isinstance(dashboards_field, forms.ModelChoiceField)
            dashboards_field.queryset = Dashboard.objects.all().filter(
                Q(user=self.user) | Q(organization__in=organizations)
            )
            dashboards_field.help_text = "Note: adding a metric to a dashboard will also add it to its organization"

    def clean(self):
        super().clean()
        if not self.data.get("dashboards") and not self.data.get("dashboard_new"):
            raise forms.ValidationError(f"Dashboard is missing")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            metric = super().save(*args, **kwargs)
            if self.data["dashboard_new"]:
                new_dashboard = Dashboard(
                    name=self.data["dashboard_new"], user=self.user
                )
                new_dashboard.save()
                metric.dashboard_set.add(new_dashboard)
            # Also make sure that for each dashboard,
            # the metric is moved to its organization if applicable
            # to keep ACL consistent
            for dashboard in metric.dashboards.all():
                if dashboard.organization:
                    metric.organizations.add(dashboard.organization)
        return metric

    class Meta:
        model = Metric
        fields = ["dashboards"]
        widgets = {
            "dashboards": forms.CheckboxSelectMultiple(),
        }
