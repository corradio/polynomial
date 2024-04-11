import math
from datetime import date, datetime, timedelta, timezone

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import BadRequest, PermissionDenied
from django.db.models import Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_date, parse_duration
from django.views.generic import CreateView, DeleteView, UpdateView

from mainapp.forms.dashboard import DashboardTransferOwnershipForm

from ..forms import DashboardForm, DashboardMetricAddForm
from ..models import Dashboard, Metric, Organization, User
from ..queries import query_measurements_without_gaps, query_topk_dates
from ..utils.charts import TOP3_MEDAL_IMAGE_PATH, get_vl_spec


@login_required
def index(request):
    user = request.user
    organizations = Organization.objects.filter(users=user)
    dashboard = (
        Dashboard.objects.all()
        .filter(Q(user=user) | Q(organization__in=organizations))
        .order_by("name")
    ).first()
    if dashboard:
        return redirect(dashboard.get_absolute_url())

    return render(request, "mainapp/dashboards.html", {})


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
    template_name = "mainapp/dashboardmetric_add.html"

    def get_success_url(self):
        return self.request.GET.get("next") or super().get_success_url()

    def dispatch(self, request, *args, **kwargs) -> HttpResponseBase:
        dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not dashboard.can_edit(request.user):
            raise PermissionDenied("You don't have the rights to edit this dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs) -> HttpResponse:
        response = super().get(request, *args, **kwargs)
        assert isinstance(response, TemplateResponse)
        assert response.context_data is not None
        # Check if the form contains any metrics to add.
        # If not, redirect to creation view directly
        dashboard = self.object
        if not response.context_data["form"].fields["metrics"].queryset:
            return redirect(
                f"{reverse('integrations')}?dashboard_ids={dashboard.pk}&next={dashboard.get_absolute_url()}"
            )
        return response

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class DashboardMetricRemoveView(LoginRequiredMixin, DeleteView):
    model = Metric
    object: Metric
    pk_url_kwarg = "metric_pk"
    template_name = "mainapp/dashboardmetric_confirm_remove.html"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["dashboard"] = self.dashboard
        return context

    def dispatch(self, request, *args, **kwargs):
        self.dashboard = get_object_or_404(Dashboard, pk=kwargs["dashboard_pk"])
        if not self.dashboard.can_delete(request.user):
            raise PermissionDenied(
                "You don't have the rights to remove a metric from this dashboard"
            )
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
        # This is a user page
        is_org_page = False
        id_query = Q(user=user, organization=None, slug=dashboard_slug)  # owned by user
    except User.DoesNotExist:
        organization = get_object_or_404(Organization, slug=username_or_org_slug)
        # This is an org page
        is_org_page = True
        id_query = Q(organization=organization, slug=dashboard_slug)  # owned by org

    # Get dashboard, will raise 404 if it does not exist
    dashboard = get_object_or_404(Dashboard, id_query)
    # Check access
    if not dashboard.can_view(request.user):
        return render(
            request,
            "mainapp/dashboard_forbidden.html",
            {"dashboard": dashboard},
            status=403,
        )
    # Query other accessible dashboards
    # if logged in: show all dashboards of one's org + user
    # if anonymous: show all public dashboards of same `username_or_org_slug` prefix
    dashboards = Dashboard.get_all_viewable_by(request.user).order_by("name")
    if isinstance(request.user, User):
        # User is not anonymous, record activity
        request.user.last_dashboard_visit = datetime.now(timezone.utc)
        request.user.save()
    else:
        # Anonymous user: don't show all public dashboard
        # ..only those who match the url prefix
        if is_org_page:
            others_query = Q(organization=organization)
        else:
            others_query = Q(user=user, organization=None)
        dashboards = dashboards.filter(others_query)

    since = request.GET.get("since", "180 days")

    start_date = None

    # Check if end_date needs to be set to something else than today()
    if since in ["current-quarter", "last-quarter"]:
        # Calculate current quarter start
        current_quarter = math.ceil(date.today().month / 3)
        current_q_start_date = date(
            year=date.today().year, month=(current_quarter - 1) * 3 + 1, day=1
        )
        if since == "last-quarter":
            # Last quarter start
            if current_q_start_date.month <= 3:
                start_date = date(year=current_q_start_date.year - 1, month=10, day=1)
            else:
                start_date = date(
                    year=current_q_start_date.year,
                    month=current_q_start_date.month - 3,
                    day=1,
                )
            end_date = current_q_start_date - timedelta(days=1)
        elif since == "current-quarter":
            start_date = current_q_start_date
            if start_date.month >= 10:
                end_date = date(year=start_date.year + 1, month=1, day=1) - timedelta(
                    days=1
                )
            else:
                end_date = date(
                    year=start_date.year, month=start_date.month + 3, day=1
                ) - timedelta(days=1)
        else:
            raise NotImplementedError
    else:
        # No quarter was passed
        end_date = date.today()
        start_date = parse_date(since)
        if not start_date:
            interval = parse_duration(since)  # e.g. "3 days"
            if not interval:
                raise BadRequest(
                    f"Invalid argument `since`: should be a date or a duration."
                )
        if interval is None:
            interval = timedelta(days=60)
        start_date = end_date - interval

    def has_outdated_measurements(metric) -> bool:
        last_non_nan_measurement = metric.last_non_nan_measurement
        if last_non_nan_measurement is None:
            return False
        days = (datetime.now(timezone.utc) - last_non_nan_measurement.updated_at).days
        return days > 14

    measurements_by_metric = [
        {
            "metric_id": metric.id,
            "metric_name": metric.name,
            "integration_id": metric.integration_id,
            "can_edit": metric.can_edit(request.user),
            "can_delete": metric.can_delete(request.user),
            "can_web_auth": metric.can_web_auth,
            "can_alter_credentials": metric.can_alter_credentials_by(request.user),
            "can_be_backfilled_by_user": metric.can_be_backfilled_by(request.user),
            "has_outdated_measurements": has_outdated_measurements(metric),
            "vl_spec": get_vl_spec(
                query_measurements_without_gaps(start_date, end_date, metric.pk),
                imageLabelUrls=dict(
                    zip(
                        query_topk_dates(metric.pk) if metric.enable_medals else [],
                        TOP3_MEDAL_IMAGE_PATH,
                    )
                ),
                markers={
                    marker.date: marker.text for marker in metric.marker_set.all()
                },
                target=metric.target,
            ),
        }
        for metric in Metric.objects.filter(dashboard=dashboard).order_by("name")
    ]
    since_options = [
        {"label": "last 10 years", "value": "3650 days"},
        {"label": "last 5 years", "value": "1825 days"},
        {"label": "last year", "value": "365 days"},
        {"label": "last 6 months", "value": "180 days"},
        {"label": "last 2 months", "value": "60 days"},
        # {"label": "last quarter", "value": "last-quarter"},
        # {"label": "current quarter", "value": "current-quarter"},
    ]
    dashboards_list = list(dashboards)
    context = {
        "measurements_by_metric": measurements_by_metric,
        "dashboard": dashboard,
        "dashboards": dashboards_list,
        "dashboard_index": (
            -1 if not dashboards_list else dashboards_list.index(dashboard)
        ),
        "can_edit": dashboard.can_edit(request.user),
        "since_options": since_options,
        "since": since,
        "since_label": [s["label"] for s in since_options if s["value"] == since][0],
    }
    return render(request, "mainapp/dashboard.html", context)


class DashboardTransferOwnershipView(LoginRequiredMixin, UpdateView):
    model = Dashboard
    form_class = DashboardTransferOwnershipForm

    def get_success_url(self):
        return self.request.GET.get("next") or reverse("index")

    def get_object(self, queryset=None) -> Dashboard:
        instance: Dashboard = super().get_object(queryset)
        if instance.can_transfer_ownership(self.request.user):
            return instance
        raise PermissionDenied(
            "Only the dashboard owner or the organization admin can transfer its ownership"
        )
