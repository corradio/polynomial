import json
import secrets
import sys
import traceback
from datetime import date, datetime, timedelta
from typing import Dict, List, Union

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
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
from integrations.models import WebAuthIntegration

from .forms import MetricForm
from .models import Measurement, Metric, User


@login_required
def index(request):
    measurements_by_metric = [
        {
            "metric_id": metric.id,
            "metric_name": metric.name,
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
def integration_collect_latest(request, integration_id):
    if request.method == "POST":
        data = json.loads(request.body)
        config = data.get("integration_config")
        config = config and json.loads(config)
        credentials = data.get("credentials")
        credentials = credentials and json.loads(credentials)
        integration_class = INTEGRATION_CLASSES[integration_id]
        try:
            new_credentials = None

            def credentials_updater(arg):
                new_credentials = arg

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
                        "newSchema": inst.callable_config_schema,
                        "newCredentials": new_credentials,
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
    return HttpResponseNotAllowed(["POST"])


@login_required
def integration_authorize(request, integration_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    config = request.POST["integration_config"]
    config = config and json.loads(config)
    # Generate a state which will identify this request
    state = secrets.token_urlsafe(16)
    # Get integration class and get the uri
    integration_class = INTEGRATION_CLASSES[integration_id]
    assert issubclass(integration_class, WebAuthIntegration)
    uri = integration_class.get_authorization_uri(
        state,
        authorize_callback_uri=request.build_absolute_uri(
            reverse("authorize-callback")
        ),
    )
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        "integration_id": integration_id,
        "integration_config": config,
    }
    return HttpResponseRedirect(uri)


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


class MetricCreateView(CreateView, LoginRequiredMixin):
    model = Metric
    form_class = MetricForm
    success_url = "/metrics"

    def get_initial(self):
        return {"integration_id": self.kwargs["integration_id"]}

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.integration_id = self.kwargs["integration_id"]
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        integration_id = self.kwargs["integration_id"]
        context["can_web_auth"] = issubclass(
            INTEGRATION_CLASSES[integration_id], WebAuthIntegration
        )
        return context


class MetricDeleteView(DeleteView, LoginRequiredMixin):  # type: ignore[misc]
    model = Metric
    success_url = reverse_lazy("metrics")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class MetricUpdateView(UpdateView, LoginRequiredMixin):
    model = Metric
    form_class = MetricForm

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.object
        context["can_web_auth"] = metric.can_web_auth
        return context


class MetricAuthorizeView(TemplateView, LoginRequiredMixin):
    def get(self, request, *args, **kwargs):
        metric = get_object_or_404(Metric, pk=self.kwargs.get("pk"), user=request.user)
        # Generate a state which will identify this request
        state = secrets.token_urlsafe(16)
        # Get integration class and get the uri
        integration_class = INTEGRATION_CLASSES[metric.integration_id]
        assert issubclass(integration_class, WebAuthIntegration)
        uri = integration_class.get_authorization_uri(
            state,
            authorize_callback_uri=request.build_absolute_uri(
                reverse("authorize-callback")
            ),
        )
        assert uri is not None
        # Save parameters in session
        self.request.session[state] = {
            "metric_id": metric.id,
        }
        return HttpResponseRedirect(uri)


class AuthorizeCallbackView(TemplateView, LoginRequiredMixin):
    def get(self, request, *args, **kwargs):
        data = self.request.GET
        state = data["state"]
        if state not in self.request.session:
            return HttpResponseBadRequest()
        else:
            obj = self.request.session[state]
            # The cache object can have either:
            # - a metric_id (if it was called from /metrics/<pk>/authorize)
            # - an integration_id (if it was called from /integrations/<id>/authorize)
            # If metric is not passed, then it needs to contain the `integration_config` object
            # in order for us to be able to create an integration instance, which is needed
            # in case we need to reload the schema dynamically
            metric = None
            if "metric_id" in obj:
                # Get integration instance
                metric = get_object_or_404(
                    Metric, pk=obj["metric_id"], user=request.user
                )
            integration_id = metric.integration_id if metric else obj["integration_id"]
            integration_class = INTEGRATION_CLASSES[integration_id]
            assert issubclass(integration_class, WebAuthIntegration)
            credentials = integration_class.process_callback(
                uri=request.build_absolute_uri(request.get_full_path()),
                state=state,
                authorize_callback_uri=request.build_absolute_uri(
                    reverse("authorize-callback")
                ),
            )
            # Clean up session
            del self.request.session[state]
            # Create credential updater
            def credentials_updater(new_credentials):
                if metric:
                    metric.credentials = new_credentials
                    metric.save()

            if metric:
                credentials_updater(credentials)
                return HttpResponseRedirect(metric.get_absolute_url())
            else:
                assert "integration_config" in obj
                integration_config = obj["integration_config"]
                # Prepare the template that will be rendered to the parent window
                # which will include credentials and updated schema
                t = Template(
                    """
                    {{ credentials|json_script:"credentials" }}
                    {{ new_schema|json_script:"new_schema" }}
                    <script>
                        var credentials = JSON.parse(document.getElementById('credentials').textContent);
                        var newSchema = JSON.parse(document.getElementById('new_schema').textContent);
                        window.opener.postMessage({ credentials, newSchema });
                        window.close();
                    </script>
                """
                )
                # Get new updated schema
                # Create instance instead of class, now that we have credentials
                with integration_class(
                    config=integration_config,
                    credentials=credentials,
                    credentials_updater=credentials_updater,
                ) as inst:
                    c = Context(
                        {
                            "credentials": credentials,
                            "new_schema": inst.callable_config_schema,
                        }
                    )
                return HttpResponse(t.render(c))
