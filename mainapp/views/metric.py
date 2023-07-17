import json
import secrets
import sys
import traceback
from datetime import date, datetime, timedelta
from types import MethodType
from typing import Any, Dict, List, Optional, Union

import requests
from allauth.account.adapter import get_adapter
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.forms.models import model_to_dict
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_date, parse_duration
from django.utils.http import urlencode
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)
from django.views.generic.detail import SingleObjectMixin

from config.settings import DEBUG
from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.base import WebAuthIntegration

from .. import forms
from ..forms import MetricForm, OrganizationForm, OrganizationUserCreateForm
from ..models import (
    Dashboard,
    Measurement,
    Metric,
    Organization,
    OrganizationInvitation,
    OrganizationUser,
    User,
)
from ..tasks import backfill_task
from .utils import add_next


def deserialize_list(arg: Optional[str]):
    if not arg:
        return []
    return arg.split(",")


def format_exception(e: Exception) -> str:
    if DEBUG:
        exc_info = sys.exc_info()
        error_str = "\n".join(traceback.format_exception(*exc_info))
    else:
        error_str = f"{str(e)}"

    if isinstance(e, requests.HTTPError):
        try:
            error_str += f"\nAdditional JSON response:\n{e.response.json()}"
        except json.decoder.JSONDecodeError:
            pass
    return error_str


@login_required
def metric_backfill(request, pk):
    # Check if user has access to metric
    metric = get_object_or_404(Metric, pk=pk)
    if not metric.can_be_backfilled_by(request.user):
        return HttpResponseForbidden()
    if request.method == "POST":
        since = request.POST.get("since")
        backfill_task.delay(metric_id=pk, since=since)
        messages.success(request, f"Data will be fetched in the background")
        return redirect(request.GET.get("next") or reverse("index"))
    elif request.method == "GET":
        return render(
            request, "mainapp/metric_confirm_backfill.html", {"object": metric}
        )
    return HttpResponseNotAllowed(["POST", "GET"])


@login_required
def metric_collect_latest(request, pk):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    try:
        with metric.integration_instance as inst:
            measurement = inst.collect_latest()
    except Exception as e:
        exc_info = sys.exc_info()
        return HttpResponseBadRequest("\n".join(traceback.format_exception(*exc_info)))
    Measurement.objects.update_or_create(
        metric=metric,
        date=measurement.date,
        defaults={
            "value": measurement.value,
        },
    )
    return HttpResponse(f"Success!")


@login_required
def metric_new_test(request, state):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    data = json.loads(request.body)
    config = data.get("integration_config")
    config = config and json.loads(config)
    # Get server side information
    metric_cache = request.session[state]["metric"]
    integration_id = metric_cache.get("integration_id")
    integration_credentials = metric_cache.get("integration_credentials")
    integration_class = INTEGRATION_CLASSES[integration_id]
    # Save the config in the cache so a page reload keeps it
    metric_cache["integration_config"] = config
    metric_cache["name"] = data.get("name")
    request.session.modified = True

    def credentials_updater(arg):
        metric_cache["integration_credentials"] = arg
        request.session.modified = True

    try:
        with integration_class(
            config,
            credentials=integration_credentials,
            credentials_updater=credentials_updater,
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    # Circumvent NaNs
                    "measurement": [
                        measurement.date,
                        str(measurement.value)
                        if measurement.value != measurement.value
                        else measurement.value,
                    ],
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        return JsonResponse(
            {
                "error": format_exception(e),
                "datetime": datetime.now(),
                "status": "error",
            }
        )


class MetricListView(LoginRequiredMixin, ListView):
    def get_queryset(self):
        # Only return metrics for integrations that actually exist
        # This is useful for developing new integrations,
        # as having data in the db without having it present on the branch
        # might crash
        return (
            Metric.objects.all()
            .filter(user=self.request.user)
            .filter(integration_id__in=INTEGRATION_IDS)
            .order_by("name")
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["INTEGRATION_CLASSES"] = INTEGRATION_CLASSES
        assert isinstance(self.request.user, User)
        context["organization_list"] = Organization.objects.filter(
            users=self.request.user
        )
        return context


@login_required
def metric_duplicate(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    # Copy object
    metric_object = model_to_dict(metric)
    metric_object["name"] = f"Copy of {metric_object['name']}"
    metric_object["dashboards"] = [d.pk for d in metric.dashboards.all()]
    metric_object["organizations"] = [o.pk for o in metric.organizations.all()]
    del metric_object["id"]
    del metric_object["user"]

    # Generate a new state to uniquely identify this new creation
    state = secrets.token_urlsafe(32)
    request.session[state] = {
        "metric": metric_object,
        "user_id": request.user.id,
    }
    return redirect(
        add_next(
            reverse("metric-new-with-state", args=[state]), request.GET.get("next")
        )
    )


@login_required
def metric_new(request):
    # Generate a new state to uniquely identify this new creation
    state = secrets.token_urlsafe(32)
    request.session[state] = {
        "metric": {
            "integration_id": request.GET["integration_id"],
            "dashboards": deserialize_list(request.GET.get("dashboard_ids")),
            "organizations": deserialize_list(request.GET.get("organization_ids")),
        },
        "user_id": request.user.id,
    }
    return redirect(
        add_next(
            reverse("metric-new-with-state", args=[state]), request.GET.get("next")
        )
    )


class MetricCreateView(LoginRequiredMixin, CreateView):
    model = Metric
    form_class = MetricForm

    def dispatch(self, request, state, *args, **kwargs):
        self.state = state
        # Make sure someone with the link can't impersonate a user
        if request.session.get(self.state, {}).get("user_id") != request.user.id:
            raise PermissionDenied
        metric_data = request.session.get(self.state, {}).get("metric", {})
        self.integration_id = metric_data.get("integration_id")
        self.integration_credentials = metric_data.get("integration_credentials")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Detect whether or not we should redirect to authorize
        integration_class = INTEGRATION_CLASSES[self.integration_id]
        can_web_auth = issubclass(integration_class, WebAuthIntegration)
        if can_web_auth and not self.integration_credentials:
            return redirect(
                reverse("metric-new-with-state-authorize", args=[self.state])
            )
        else:
            return super().get(request, *args, **kwargs)

    def get_initial(self):
        data = self.request.session.get(self.state)
        if data is None:
            return redirect(reverse("metric_new", args=[self.integration_id]))
        # Restore form
        initial = data.get("metric", {"integration_id": self.integration_id})
        assert initial["integration_id"] == self.integration_id
        return initial

    def get_success_url(self):
        assert self.object is not None
        next_destination = self.request.GET.get("next") or reverse("index")
        if not self.object.dashboard_set.count():
            # Make sure we ask if we should add to dashboard at the end
            next_destination = add_next(
                reverse("metricdashboard_add", args=[self.object.pk]),
                next=next_destination,
                encode=True,
            )
        if not self.object.measurement_set.count() and self.object.can_backfill:
            # Metric has no measurements, first propose user to backfill
            next_destination = add_next(
                reverse("metric-backfill", args=[self.object.pk]),
                next=next_destination,
                encode=True,
            )
        return next_destination

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        # The callable schema will require an initialised instance that will get
        # passed to it.
        # Furthermore, getting the schema from the form might cause credential
        # updates. We therefore need to pass an instance of a Metric
        # object which is capable of updating the cached credentials
        kwargs["instance"] = Metric(
            # Note we have to exclude relations from initialization params
            **{
                k: v
                for (k, v) in kwargs["initial"].items()
                if k not in ["dashboards", "organizations"]
            }
        )

        def credentials_saver(metric_instance):
            metric = self.request.session[self.state]["metric"]
            metric["integration_credentials"] = metric_instance.integration_credentials
            self.request.session[self.state] = {
                **self.request.session[self.state],
                "metric": metric,
            }

        kwargs["instance"].save_credentials = MethodType(
            credentials_saver, kwargs["instance"]
        )
        return kwargs

    def form_valid(self, form):
        # This happens when the user saves the form
        # Here we build the Metric instance (`form.instance`)
        form.instance.user = self.request.user
        # Add hidden (server only) fields
        form.instance.integration_credentials = self.integration_credentials
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_web_auth"] = issubclass(
            INTEGRATION_CLASSES[self.integration_id], WebAuthIntegration
        )
        return context


@login_required
def metric_new_authorize(request, state):
    # Get session state
    metric_data = request.session[state]["metric"]
    integration_id = metric_data["integration_id"]
    # Get integration class and get the uri
    integration_class = INTEGRATION_CLASSES[integration_id]
    assert issubclass(integration_class, WebAuthIntegration)
    uri, code_verifier = integration_class.get_authorization_uri_and_code_verifier(
        state,
        authorize_callback_uri=request.build_absolute_uri(
            reverse("authorize-callback")
        ),
    )
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        **request.session[state],
        "code_verifier": code_verifier,
        "next": request.GET.get("next"),
    }
    return HttpResponseRedirect(uri)


class MetricDeleteView(LoginRequiredMixin, DeleteView):
    object: Metric
    model = Metric

    def get_success_url(self):
        return self.request.GET.get("next") or reverse("index")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class MetricUpdateView(LoginRequiredMixin, UpdateView):
    model = Metric
    form_class = MetricForm

    def get_success_url(self):
        next_destination = self.request.GET.get("next") or reverse("index")
        if not self.object.dashboard_set.count():
            # Make sure we ask if we should add to dashboard at the end
            next_destination = add_next(
                reverse("metricdashboard_add", args=[self.object.pk]),
                next=next_destination,
                encode=True,
            )
        if not self.object.measurement_set.count() and self.object.can_backfill:
            # Metric has no measurements, first propose user to backfill
            next_destination = add_next(
                reverse("metric-backfill", args=[self.object.pk]),
                next=next_destination,
                encode=True,
            )
        return next_destination

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.object
        context["can_web_auth"] = metric.can_web_auth
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


@login_required
def metric_authorize(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    integration_id = metric.integration_id
    # Get integration class and get the uri
    integration_class = INTEGRATION_CLASSES[integration_id]
    assert issubclass(integration_class, WebAuthIntegration)
    # Generate state to uniquely identify this request
    state = secrets.token_urlsafe(32)
    uri, code_verifier = integration_class.get_authorization_uri_and_code_verifier(
        state,
        authorize_callback_uri=request.build_absolute_uri(
            reverse("authorize-callback")
        ),
    )
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        "metric_id": metric.id,
        "code_verifier": code_verifier,
        "next": request.GET.get("next"),
    }
    return HttpResponseRedirect(uri)


@login_required
def metric_test(request, pk):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    data = json.loads(request.body)
    config = data.get("integration_config")
    config = config and json.loads(config)
    # Get server side information
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    integration_id = metric.integration_id
    integration_credentials = metric.integration_credentials
    integration_class = INTEGRATION_CLASSES[integration_id]

    def credentials_updater(arg):
        metric.integration_credentials = arg
        metric.save()

    try:
        with integration_class(
            config,
            credentials=integration_credentials,
            credentials_updater=credentials_updater,
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    # Circumvent NaNs
                    "measurement": [
                        measurement.date,
                        str(measurement.value)
                        if measurement.value != measurement.value
                        else measurement.value,
                    ],
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        return JsonResponse(
            {
                "error": format_exception(e),
                "datetime": datetime.now(),
                "status": "error",
            }
        )


class MetricImportView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Metric
    form_class = forms.MetricImportForm
    success_message = "%(num_rows)s values imported"
    template_name = "mainapp/metric_import.html"

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("index")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class MetricIntegrationUpdateView(LoginRequiredMixin, UpdateView):
    model = Metric
    form_class = forms.MetricIntegrationForm
    template_name = "mainapp/metric_select_integration.html"

    def get_success_url(self):
        if self.object.can_web_auth and not self.object.integration_credentials:
            return reverse("metric-authorize", args=[self.object.pk])
        return self.request.GET.get("next") or self.object.get_absolute_url()

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class NewMetricIntegrationCreateView(LoginRequiredMixin, CreateView):
    # Use a create view as form will not be able to fetch existing model
    model = Metric
    form_class = forms.MetricIntegrationForm
    template_name = "mainapp/metric_select_integration.html"

    def dispatch(self, request, state, *args, **kwargs):
        self.state = state
        # Make sure someone with the link can't impersonate a user
        if request.session.get(self.state, {}).get("user_id") != request.user.id:
            raise PermissionDenied
        metric_data = request.session.get(self.state, {}).get("metric", {})
        self.integration_id = metric_data.get("integration_id")
        self.integration_credentials = metric_data.get("integration_credentials")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        metric_data = self.request.session.get(self.state, {}).get("metric", {})
        integration_id = metric_data.get("integration_id")
        can_web_auth = issubclass(
            INTEGRATION_CLASSES[integration_id], WebAuthIntegration
        )
        if can_web_auth and not self.integration_credentials:
            return reverse("metric-new-with-state-authorize", args=[self.state])
        return self.request.GET.get("next") or reverse(
            "metric-new-with-state", args=[self.state]
        )

    def get_initial(self):
        return {"integration_id": self.integration_id}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        kwargs["state"] = self.state
        return kwargs


class MetricDashboardAddView(LoginRequiredMixin, UpdateView):
    model = Metric
    form_class = forms.MetricDashboardAddForm
    template_name = "mainapp/metricdashboard_add.html"

    def get_success_url(self):
        return self.request.GET.get("next") or super().get_success_url()

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs
