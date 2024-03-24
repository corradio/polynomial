import csv
from datetime import date, datetime
from io import TextIOWrapper
from typing import List

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import Q

from mainapp.models import Dashboard, Measurement, Metric, Organization

from .base import BaseModelForm


class MetricForm(BaseModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        # manually set the current instance on the widget
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        self.fields["integration_config"].widget.instance = self.instance

        if self.instance.pk and not self.instance.can_edit(self.user):
            for field in self.fields.values():
                field.disabled = True

        organization_field = self.fields["organization"]
        assert isinstance(organization_field, forms.ModelChoiceField)
        organizations = Organization.objects.filter(users=self.user)
        organization_field.queryset = Organization.objects.filter(users=self.user)
        organization_field.help_text = "Sharing a metric with an organization will make it usable by all its members"

        if "dashboards" in self.fields:
            dashboards_field = self.fields["dashboards"]
            assert isinstance(dashboards_field, forms.ModelChoiceField)
            dashboards_field.queryset = Dashboard.objects.all().filter(
                Q(user=self.user) | Q(organization__in=organizations)
            )
            dashboards_field.help_text = (
                "Adding a metric to a dashboard will also add it to its organization"
            )

    def save(self, *args, **kwargs) -> Metric:
        if not self.instance.can_edit(self.user):
            raise PermissionDenied()
        metric: Metric = super().save(*args, **kwargs)
        # Also make sure that for each dashboard,
        # the metric is moved to its organization if applicable
        # to keep ACL consistent
        for dashboard in metric.dashboards.all():
            metric.organization = dashboard.organization
        return metric

    @property
    def media(self):
        # Hack to make sure the CSS styles do not propagate
        media = super().media
        return forms.Media(js=media._js)

    class Meta:
        model = Metric
        fields = [
            "name",
            "organization",
            "enable_medals",
            "higher_is_better",
            "integration_config",
            "integration_id",
            # The following are required to be able to save that info when creating
            "dashboards",
        ]

        widgets = {
            "integration_id": forms.HiddenInput(),
            "dashboards": forms.MultipleHiddenInput(),
            "organization": forms.Select(),
            "higher_is_better": forms.Select(
                choices=(
                    (True, "Higher values are better"),
                    (False, "Lower values are better"),
                )
            ),
        }


class MetricImportForm(BaseModelForm):
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


class MetricTransferOwnershipForm(BaseModelForm):
    def __init__(self, *args, **kwargs):
        super(MetricTransferOwnershipForm, self).__init__(*args, **kwargs)

        # To avoid leaking all org users, we only show the ones in the organisation
        users = sorted(
            self.instance.organization.users.all(),
            key=lambda u: str(u),
        )
        self.fields["user"].widget = forms.Select(choices=[(u.pk, u) for u in users])

    class Meta:
        model = Metric
        fields = [
            "user",
        ]


class MetricIntegrationForm(BaseModelForm):
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
            else:
                # Creating metric, i.e. use the cache
                metric_cache = self.request.session[self.state]["metric"]
                metric_cache["integration_credentials"] = None
                metric_cache["integration_config"] = None
                metric_cache["integration_id"] = self.cleaned_data["integration_id"]
                self.request.session.modified = True
        return super().save(*args, **kwargs)

    class Meta:
        model = Metric
        fields = ["integration_id"]


class MetricDashboardAddForm(BaseModelForm):
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

    def save(self, *args, **kwargs) -> Metric:
        with transaction.atomic():
            metric: Metric = super().save(*args, **kwargs)
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
                metric.organization = dashboard.organization
        return metric

    class Meta:
        model = Metric
        fields = ["dashboards"]
        widgets = {
            "dashboards": forms.CheckboxSelectMultiple(),
        }
