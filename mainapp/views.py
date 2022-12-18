import json
import sys
import traceback

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS

from .forms import MetricForm
from .models import Measurement, Metric, User


# TODO: Refactor
def get_integration_implementation(metric):
    # TODO: Read secrets from store
    import os

    secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
    config = metric.integration_config and json.loads(metric.integration_config)
    integration_class = INTEGRATION_CLASSES[metric.integration_id]
    inst = integration_class(config, secrets)
    return inst


@login_required
def index(request):
    measurements = [
        {
            "metric": measurement.metric.name,
            "value": measurement.value,
            "date": measurement.date.isoformat(),
        }
        for measurement in Measurement.objects.filter(metric__user=request.user)
    ]
    context = {
        "measurements": measurements,
        "unique_metrics": sorted(set([d["metric"] for d in measurements])),
    }
    return render(request, "mainapp/index.html", context)


# TODO: Refactor this route
@login_required
def metric_collect(request, metric_id):
    metric = get_object_or_404(Metric, pk=metric_id, user=request.user)
    try:
        if request.GET.get("since"):
            from django.utils.dateparse import parse_date

            since = parse_date(request.GET.get("since"))
            # Note: we could also use parse_duration() and pass e.g. "3 days"
            from datetime import date, timedelta

            data = get_integration_implementation(metric).collect_past_multi(
                date_start=since, date_end=date.today() - timedelta(days=1)
            )
            # Save in this case
            for measurement in data:
                Measurement.objects.update_or_create(
                    metric=metric,
                    date=measurement.date,
                    defaults={
                        "value": measurement.value,
                        "metric": metric,
                    },
                )
        else:
            data = get_integration_implementation(metric).collect_latest()
            # TODO: Should this route change the DB?
            # Should it be another VERB?
            # Measurement.objects.update_or_create(
            #     metric=metric,
            #     date=measurement.date,
            #     defaults={"value": measurement.value},
            # )
    except Exception as e:
        import sys
        import traceback

        exc_info = sys.exc_info()
        return JsonResponse(
            {
                "error": "\n".join(traceback.format_exception(*exc_info)),
                "status": "error",
            },
            status=500,
        )
    return JsonResponse(
        {
            "data": data,
            "status": "ok",
        }
    )


@login_required
def integration_collect_latest(request, integration_id):
    if request.method == "POST":
        data = json.loads(request.body)
        config = data.get("integration_config")
        config = config and json.loads(config)
        # TODO: Read secrets from POST
        import os

        secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
        integration_class = INTEGRATION_CLASSES[integration_id]
        inst = integration_class(config, secrets)
        try:
            measurement = inst.collect_latest()
            return JsonResponse({"measurement": measurement, "status": "ok"})
        except Exception as e:
            exc_info = sys.exc_info()
            error_str = "\n".join(traceback.format_exception(*exc_info))
            return JsonResponse({"error": error_str, "status": "error"})
    return HttpResponseNotAllowed(["POST"])


class IntegrationListView(ListView):
    # this page should be unprotected for SEO purposes
    template_name = "mainapp/integration_list.html"

    def get_queryset(self):
        return INTEGRATION_IDS


class MetricListView(ListView, LoginRequiredMixin):
    def get_queryset(self):
        return Metric.objects.filter(user=self.request.user).order_by("name")


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
