import json
import secrets
import sys
import traceback
from datetime import date, datetime, timedelta
from types import MethodType
from typing import Dict, List, Union

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_date, parse_duration
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    TemplateView,
    UpdateView,
)

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.base import WebAuthIntegration

from .forms import MetricForm
from .models import Measurement, Metric, User


@login_required
def index(request):
    measurements_by_metric = [
        {
            "metric_id": metric.id,
            "metric_name": metric.name,
            "integration_id": metric.integration_id,
            "measurements": [
                {
                    "value": measurement.value,
                    "date": measurement.date.isoformat(),
                }
                for measurement in Measurement.objects.filter(metric=metric).order_by(
                    "date"
                )
            ],
        }
        for metric in Metric.objects.filter(user=request.user).order_by("name")
    ]
    context = {
        "measurements_by_metric": measurements_by_metric,
    }
    return render(request, "mainapp/index.html", context)


@login_required
def metric_backfill(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    if not request.POST.get("since"):
        return HttpResponseBadRequest("Field `since` or `duration` is required.")
    start_date = parse_date(request.POST["since"])
    if not start_date:
        interval = parse_duration(request.POST["since"])
    if not interval:
        return HttpResponseBadRequest(
            f"Invalid argument `since`: should be a date or a duration."
        )
    start_date = date.today() - interval
    # Note: we could also use parse_duration() and pass e.g. "3 days"
    try:
        with metric.integration_instance as inst:
            measurements = inst.collect_past_range(
                date_start=max(start_date, inst.earliest_backfill()),
                date_end=date.today() - timedelta(days=1),
            )
    except Exception as e:
        exc_info = sys.exc_info()
        return HttpResponseServerError("\n".join(traceback.format_exception(*exc_info)))
    # Save
    for measurement in measurements:
        Measurement.objects.update_or_create(
            metric=metric,
            date=measurement.date,
            defaults={
                "value": measurement.value,
                "metric": metric,
            },
        )
    return HttpResponse(f"{len(measurements)} collected!")


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
        return HttpResponseServerError("\n".join(traceback.format_exception(*exc_info)))
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
    credentials = metric_cache.get("credentials")
    integration_class = INTEGRATION_CLASSES[integration_id]
    # Save the config in the cache so a page reload keeps it
    metric_cache["integration_config"] = config
    request.session.modified = True

    def credentials_updater(arg):
        metric_cache["credentials"] = arg
        request.session.modified = True

    try:
        with integration_class(
            config, credentials=credentials, credentials_updater=credentials_updater
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    "measurement": measurement,
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        if False:
            exc_info = sys.exc_info()
            error_str = "\n".join(traceback.format_exception(*exc_info))
        else:
            error_str = f"{type(e).__name__}: {str(e)}"
        return JsonResponse(
            {"error": error_str, "datetime": datetime.now(), "status": "error"}
        )


class IntegrationListView(ListView):
    # this page should be unprotected for SEO purposes
    template_name = "mainapp/integration_list.html"

    def get_queryset(self):
        return INTEGRATION_IDS


class MetricListView(ListView, LoginRequiredMixin):
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
        return context


@login_required
def metric_new(request):
    # Generate a new state to uniquely identify this new creation
    state = secrets.token_urlsafe(32)
    integration_id = request.GET["integration_id"]
    request.session[state] = {
        "metric": {"integration_id": integration_id},
        "user_id": request.user.id,
    }
    return redirect(reverse("metric-new-with-state", args=[state]))


class MetricCreateView(CreateView, LoginRequiredMixin):
    model = Metric
    form_class = MetricForm
    success_url = reverse_lazy("metrics")

    def dispatch(self, request, state, *args, **kwargs):
        self.state = state
        # Make sure someone with the link can't impersonate a user
        if request.session.get(self.state, {}).get("user_id") != request.user.id:
            return HttpResponseForbidden()
        metric_data = request.session.get(self.state, {}).get("metric", {})
        self.integration_id = metric_data.get("integration_id")
        self.credentials = metric_data.get("credentials")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Detect whether or not we should redirect to authorize
        integration_class = INTEGRATION_CLASSES[self.integration_id]
        can_web_auth = issubclass(integration_class, WebAuthIntegration)
        if can_web_auth and not self.credentials:
            return redirect(
                reverse("metric-new-with-state-authorize", args=[self.state])
            )
        else:
            return super().get(request, *args, **kwargs)

    def get_initial(self):
        data = self.request.session.get(self.state)
        if data is None:
            return redirect(reverse("metric-new", args=[self.integration_id]))
        # Restore form
        initial = data.get("metric", {"integration_id": self.integration_id})
        assert initial["integration_id"] == self.integration_id
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # The callable schema will require an initialised instance that will get
        # passed to it.
        # Furthermore, getting the schema from the form might cause credential
        # updates. We therefore need to pass an instance of a Metric
        # object which is capable of updating the cached credentials
        kwargs["instance"] = Metric(**kwargs["initial"])

        def credentials_saver(metric_instance):
            metric = self.request.session[self.state]["metric"]
            metric["credentials"] = metric_instance.credentials
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
        form.instance.credentials = self.credentials
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
    }
    return HttpResponseRedirect(uri)


class MetricDeleteView(DeleteView, LoginRequiredMixin):  # type: ignore[misc]
    model = Metric
    success_url = reverse_lazy("metrics")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class MetricUpdateView(UpdateView, LoginRequiredMixin):
    model = Metric
    form_class = MetricForm
    success_url = reverse_lazy("metrics")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.object
        context["can_web_auth"] = metric.can_web_auth
        return context


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
    credentials = metric.credentials
    integration_class = INTEGRATION_CLASSES[integration_id]

    def credentials_updater(arg):
        metric.credentials = arg
        metric.save()

    try:
        with integration_class(
            config, credentials=credentials, credentials_updater=credentials_updater
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    "measurement": measurement,
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        if True:
            exc_info = sys.exc_info()
            error_str = "\n".join(traceback.format_exception(*exc_info))
        else:
            error_str = f"{type(e).__name__}: {str(e)}"
        return JsonResponse(
            {"error": error_str, "datetime": datetime.now(), "status": "error"}
        )


class AuthorizeCallbackView(TemplateView, LoginRequiredMixin):
    def get(self, request, *args, **kwargs):
        state = self.request.GET["state"]
        if state not in self.request.session:
            return HttpResponseBadRequest()
        else:
            cache_obj = self.request.session[state]
            # The cache object can have either:
            # - a metric_id (if it was called from /metrics/<pk>/authorize)
            # - Nothing (if it was called from /metrics/new/<state>/authorize)
            metric = None
            if "metric_id" in cache_obj:
                # Get integration instance
                metric = get_object_or_404(
                    Metric, pk=cache_obj["metric_id"], user=request.user
                )
            integration_id = (
                metric.integration_id
                if metric
                else cache_obj["metric"]["integration_id"]
            )
            integration_class = INTEGRATION_CLASSES[integration_id]
            assert issubclass(integration_class, WebAuthIntegration)
            credentials = integration_class.process_callback(
                uri=request.build_absolute_uri(request.get_full_path()),
                state=state,
                authorize_callback_uri=request.build_absolute_uri(
                    reverse("authorize-callback")
                ),
                code_verifier=cache_obj.get("code_verifier"),
            )
            # Save credentials
            if metric:
                metric.credentials = credentials
                metric.save()
                # Clean up session as it won't be used anymore
                del self.request.session[state]
                return redirect(metric)
            else:
                cache_obj["metric"]["credentials"] = credentials
                request.session.modified = True
                return redirect(reverse("metric-new-with-state", args=[state]))
