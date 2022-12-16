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
    measurement = collect(integration_instance.integration_id)
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

    # show edit page
    form = IntegrationInstanceForm(instance=integration_instance)

    from django.template import Context, Template

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
    context = Context(
        {
            "form": form,
        }
    )

    return HttpResponse(template.render(context))
