from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from integrations.collector import collect

from .forms import IntegrationInstanceForm
from .models import IntegrationInstance, Measurement, User


def index(request):
    return HttpResponse("ok")


@login_required
def integration_instance(request, integration_instance_id):
    integration_instance = get_object_or_404(
        IntegrationInstance, pk=integration_instance_id, metric__user=request.user
    )

    # # collect
    # measurement = collect(integration_instance.name)
    # Measurement.objects.update_or_create(
    #     metric=integration_instance.metric,
    #     date=measurement.date,
    #     defaults={"value": measurement.value},
    # )
    # return HttpResponse(measurement)

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
