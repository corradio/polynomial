from django import forms
from django.db.models import Q

from mainapp.models import Dashboard, Metric, Organization

from .base import BaseModelForm


class DashboardForm(BaseModelForm):
    def __init__(self, *args, **kwargs) -> None:
        request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        user = request.user
        organization_field = self.fields["organization"]
        assert isinstance(organization_field, forms.ModelChoiceField)
        organization_field.queryset = Organization.objects.filter(users=user)
        organization_field.help_text = "Dashboard and associated metrics will be made accessible to all organization members"
        # Also make a dict with slugs available for template
        self.org_slugs = {o.pk: o.slug for o in organization_field.queryset}

    def save(self, *args, **kwargs) -> Dashboard:
        dashboard = super().save(*args, **kwargs)
        # Also make sure that every metric of this dashboard is moved
        # to the organization to keep ACL consistent
        if dashboard.organization:
            for metric in dashboard.metrics.all():
                metric.organization = dashboard.organization
        return dashboard

    class Meta:
        model = Dashboard
        fields = ["name", "slug", "is_public", "user", "organization"]

        widgets = {
            # Make this field available to the form but invisible to user
            "user": forms.HiddenInput(),
        }


class DashboardMetricAddForm(BaseModelForm):
    def __init__(self, *args, **kwargs) -> None:
        user = kwargs.pop("user")
        integration_id = kwargs.pop("integration_id", None)
        super().__init__(*args, **kwargs)
        organizations = Organization.objects.filter(users=user)
        available_metrics = (
            Metric.objects.all()
            .filter(Q(user=user) | Q(organization__in=organizations))
            .exclude(dashboard=self.instance)
            .order_by("integration_id", "name")
        )
        if integration_id:
            available_metrics = available_metrics.filter(integration_id=integration_id)
        metrics_field = self.fields["metrics"]
        assert isinstance(metrics_field, forms.ModelChoiceField)
        metrics_field.queryset = available_metrics
        if self.instance.organization:
            metrics_field.help_text = f"Note: metrics selected will automatically be added to the {self.instance.organization} organization"

    def save(self, *args, **kwargs):
        # Join form metrics to be added with existing metrics
        self.cleaned_data["metrics"] |= self.instance.metrics.all()
        dashboard = super().save(*args, **kwargs)
        # Ensure the metric belongs to the organisation of its dashboard.
        # Leave intact if this dashboard is not in an org
        # Note: this should be kept in sync with MetricBaseForm (reverse)
        if dashboard.organization:
            for metric in dashboard.metrics.all():
                metric.organization = dashboard.organization
                metric.save()
        return dashboard

    class Meta:
        model = Dashboard
        fields = ["metrics"]
        widgets = {
            "metrics": forms.CheckboxSelectMultiple(),
        }


class DashboardTransferOwnershipForm(BaseModelForm):
    def __init__(self, *args, **kwargs) -> None:
        super(DashboardTransferOwnershipForm, self).__init__(*args, **kwargs)

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
