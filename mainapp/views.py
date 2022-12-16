import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from integrations.collector import collect

from .forms import IntegrationInstanceForm
from .models import IntegrationInstance, Measurement, Metric, User


@login_required
def index(request):
    data = {
        m: Measurement.objects.all().filter(metric=m)
        for m in Metric.objects.all().filter(user=request.user)
    }
    return HttpResponse(
        "<br />".join(
            [f"{k}: [{','.join([str(v) for v in v])}]" for k, v in data.items()]
        )
    )


@login_required
def integration_instance_collect(request, integration_instance_id):
    integration_instance = get_object_or_404(
        IntegrationInstance, pk=integration_instance_id, metric__user=request.user
    )
    # TODO: Read secrets from store
    import os

    secrets = {"PLAUSIBLE_API_KEY": os.environ["PLAUSIBLE_API_KEY"]}
    config = json.loads(integration_instance.config)
    measurement = collect(
        integration_instance.integration_id, config=config, secrets=secrets
    )
    Measurement.objects.update_or_create(
        metric=integration_instance.metric,
        date=measurement.date,
        defaults={"value": measurement.value},
    )
    return HttpResponse(measurement)


@login_required
def integration_instance(request, integration_instance_id):
    integration_instance = get_object_or_404(
        IntegrationInstance, pk=integration_instance_id, metric__user=request.user
    )

    if request.POST:
        # TODO: use generic views instead
        # from django.views import generic
        # https://docs.djangoproject.com/en/4.1/intro/tutorial04/#use-generic-views-less-code-is-better
        integration_instance.config = request.POST["config"]
        integration_instance.secrets = request.POST["secrets"]
        # Hack. TODO: Fix
        if (integration_instance.config or "null") == "null":
            integration_instance.config = None
        if (integration_instance.secrets or "null") == "null":
            integration_instance.secrets = None
        integration_instance.save()
        return HttpResponse("ok")

    # show edit page
    form = IntegrationInstanceForm(instance=integration_instance)

    from django.template import RequestContext, Template

    template = Template(
        """
{% extends "base.html" %}
{% block content %}
  <form action="" method="post">
    {% csrf_token %}
    {{ form.media }}
    {{ form }}
    <input type="submit" value="Submit">
  </form>
{% endblock %}
        """
    )
    context = RequestContext(
        request,
        {
            "form": form,
        },
    )
    return HttpResponse(template.render(context))
