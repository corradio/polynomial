from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date, parse_duration
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from ..forms import DashboardUpdateForm
from ..models import Dashboard, Measurement, Metric, Organization, User
from .mixins import DashboardEditRightsRequiredMixin


class DashboardCreateView(LoginRequiredMixin, CreateView):
    # TODO: ACL
    model = Dashboard


class DashboardDeleteView(LoginRequiredMixin, DeleteView):
    # TODO: ACL
    model = Dashboard
    pk_url_kwarg = "dashboard_pk"
    object: Dashboard


class DashboardUpdateView(
    LoginRequiredMixin, DashboardEditRightsRequiredMixin, UpdateView
):
    model = Dashboard
    pk_url_kwarg = "dashboard_pk"
    form_class = DashboardUpdateForm


def dashboard_view(request, username_or_org_slug, dashboard_slug):
    try:
        user = User.objects.get(username=username_or_org_slug)
        page_name = user.name
        id_query = Q(user=user, slug=dashboard_slug)  # owned by user
    except User.DoesNotExist:
        # try org slug
        organization = get_object_or_404(Organization, slug=username_or_org_slug)
        page_name = organization.name
        id_query = Q(organization=organization, slug=dashboard_slug)  # owned by org

    organizations = Organization.objects.filter(users=request.user)
    dashboard = get_object_or_404(
        Dashboard,
        id_query
        # Either owner, public dashboard, or member of dashboard org
        & Q(user=request.user) | Q(is_public=True) | Q(organization__in=organizations),
    )

    start_date = None
    if "since" in request.GET:
        start_date = parse_date(request.GET["since"])
        if not start_date:
            interval = parse_duration(request.GET["since"])  # e.g. "3 days"
            if not interval:
                return HttpResponseBadRequest(
                    f"Invalid argument `since`: should be a date or a duration."
                )
            start_date = date.today() - interval
    if start_date is None:
        start_date = date.today() - timedelta(days=60)
    end_date = date.today()
    measurements_by_metric = [
        {
            "metric_id": metric.id,
            "metric_name": metric.name,
            "integration_id": metric.integration_id,
            "can_edit": metric.can_edit(request.user),
            "measurements": [
                {
                    "value": measurement.value,
                    "date": measurement.date.isoformat(),
                }
                for measurement in Measurement.objects.filter(
                    metric=metric, date__range=[start_date, end_date]
                ).order_by("date")
            ],
        }
        for metric in Metric.objects.filter(dashboard=dashboard).order_by("name")
    ]
    context = {
        "measurements_by_metric": measurements_by_metric,
        "start_date": start_date,
        "end_date": end_date,
        "dashboard": dashboard,
        "can_edit": dashboard.can_edit(request.user),
    }
    return render(request, "mainapp/dashboard.html", context)
