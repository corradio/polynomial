import json
import sys
import traceback

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.generic import CreateView, FormView, ListView, UpdateView

from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS

from .forms import MetricForm
from .models import Measurement, Metric, User


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
    data = [
        {
            "metric": measurement.metric.name,
            "value": measurement.value,
            "date": measurement.date.isoformat(),
        }
        for measurement in Measurement.objects.filter(metric__user=request.user)
    ]
    context = {
        "json_data": json.dumps(data),
        "json_unique_metrics": json.dumps(sorted(set([d["metric"] for d in data]))),
    }
    return render(request, "mainapp/index.html", context)


@login_required
def metric_collect(request, metric_id):
    metric = get_object_or_404(Metric, pk=metric_id, user=request.user)
    try:
        if request.GET.get("since"):
            from django.utils.dateparse import parse_date

            since = parse_date(request.GET.get("since"))
            # Note: we could also use parse_duration() and pass e.g. "3 days"
            from datetime import date, timedelta

            dates = [date.today() - timedelta(days=1)]  # start with yesterday
            while True:
                new_date = dates[-1] - timedelta(days=1)
                if new_date < since:
                    break
                else:
                    dates.append(new_date)
            data = get_integration_implementation(metric).collect_past_multi(dates)
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
def metric_details(request, metric_id):
    if metric_id:
        metric = get_object_or_404(Metric, pk=metric_id, user=request.user)

        integration_error = None
        measurement = None
        if request.POST:
            # TODO: use generic views instead
            # from django.views import generic
            # https://docs.djangoproject.com/en/4.1/intro/tutorial04/#use-generic-views-less-code-is-better
            metric.integration_config = request.POST["integration_config"]
            metric.integration_secrets = request.POST["integration_secrets"]
            # Hack. TODO: Fix
            if (metric.integration_config or "null") == "null":
                metric.integration_config = None
            if (metric.integration_secrets or "null") == "null":
                metric.integration_secrets = None
            # Test the integration before saving it
            try:
                measurement = get_integration_implementation(metric).collect_latest()
            except Exception as e:
                exc_info = sys.exc_info()
                integration_error = "\n".join(traceback.format_exception(*exc_info))
            # If the test is conclusive, save
            if measurement:
                metric.save()

        # show edit page
        form = MetricForm(instance=metric)
    else:
        form = MetricForm()

    from django.template import RequestContext, Template

    template = Template(
        """
{% extends "base.html" %}
{% block content %}
  <form action="" method="post">
    {% csrf_token %}
    {{ form.media }}
    {{ form }}
    <input type="submit" value="Test and save">
    <p>
        {% if integration_error %}
        <div style="color: red">Error while collecting integration. Settings have not been saved.<br/><pre>{{ integration_error }}</pre></div>
        {% else %}
        <div style="color: green">Integration returned {{ measurement }}. Settings have been saved.</div>
        {% endif %}
    </p>
  </form>
{% endblock %}
        """
    )
    context = RequestContext(
        request,
        {
            "form": form,
            "integration_error": integration_error,
            "measurement": measurement,
        },
    )
    return HttpResponse(template.render(context))


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


class MetricUpdateView(UpdateView, LoginRequiredMixin):
    model = Metric
    form_class = MetricForm

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)
