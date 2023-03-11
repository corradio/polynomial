from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_date, parse_duration
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from ..forms import DashboardForm, DashboardMetricAddForm
from ..models import Dashboard, Measurement, Metric, Organization, User


class DashboardCreateView(LoginRequiredMixin, CreateView):
    model = Dashboard
    form_class = DashboardForm

    def get_initial(self):
        return {"user": self.request.user}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


class DashboardDeleteView(LoginRequiredMixin, DeleteView):
    model = Dashboard
    pk_url_kwarg = "dashboard_pk"
    object: Dashboard

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("index")

    def dispatch(self, request, *args, **kwargs):
        dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not dashboard.can_delete(request.user):
            raise PermissionDenied("You don't have the rights to delete this dashboard")
        return super().dispatch(request, *args, **kwargs)


class DashboardUpdateView(LoginRequiredMixin, UpdateView):
    model = Dashboard
    pk_url_kwarg = "dashboard_pk"
    form_class = DashboardForm

    def dispatch(self, request, *args, **kwargs):
        dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not dashboard.can_edit(request.user):
            raise PermissionDenied("You don't have the rights to edit this dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


class DashboardMetricAddView(LoginRequiredMixin, UpdateView):
    model = Dashboard
    pk_url_kwarg = "dashboard_pk"
    form_class = DashboardMetricAddForm

    def dispatch(self, request, *args, **kwargs):
        dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not dashboard.can_edit(request.user):
            raise PermissionDenied("You don't have the rights to edit this dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class DashboardMetricRemoveView(LoginRequiredMixin, DeleteView):
    model = Metric
    object: Metric
    pk_url_kwarg = "metric_pk"
    template_name = "mainapp/dashboardmetric_confirm_remove.html"

    def dispatch(self, request, *args, **kwargs):
        self.dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not self.dashboard.can_delete(request.user):
            raise PermissionDenied("You don't have the rights to delete this dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return self.request.GET.get("next") or self.dashboard.get_absolute_url()

    def form_valid(self, form):
        success_url = self.get_success_url()
        self.dashboard.metrics.remove(self.object)
        return HttpResponseRedirect(success_url)


def dashboard_view(request: HttpRequest, username_or_org_slug, dashboard_slug):
    try:
        user = User.objects.get(username=username_or_org_slug)
        page_name = user.name
        id_query = Q(user=user, slug=dashboard_slug)  # owned by user
    except User.DoesNotExist:
        # try org slug
        organization = get_object_or_404(Organization, slug=username_or_org_slug)
        page_name = organization.name
        id_query = Q(organization=organization, slug=dashboard_slug)  # owned by org

    if isinstance(request.user, User):
        organizations = Organization.objects.filter(users=request.user)
        dashboard = get_object_or_404(
            Dashboard,
            id_query
            # Either owner, or member of dashboard org
            & (Q(user=request.user) | Q(organization__in=organizations)),
        )
    else:
        # Anonymous user
        dashboard = get_object_or_404(Dashboard, id_query & Q(is_public=True))

    start_date = None
    interval = None
    if "since" in request.GET:
        start_date = parse_date(request.GET["since"])
        if not start_date:
            interval = parse_duration(request.GET["since"])  # e.g. "3 days"
            if not interval:
                return HttpResponseBadRequest(
                    f"Invalid argument `since`: should be a date or a duration."
                )
    if interval is None:
        interval = timedelta(days=60)
    end_date = date.today()
    start_date = end_date - interval
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
        "days_since": interval.days,
    }
    return render(request, "mainapp/dashboard.html", context)
