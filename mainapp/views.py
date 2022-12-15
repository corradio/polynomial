from django.contrib.auth.decorators import login_required
from django.forms import ModelForm
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from mainapp.models import IntegrationConfig, IntegrationInstance, User

from .integrations.collector import collect


class IntegrationConfigForm(ModelForm):
    class Meta:
        model = IntegrationConfig
        fields = ["items"]


def index(request):
    # return HttpResponse(collect("plausible"))

    form = IntegrationConfigForm()

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


@login_required
def integration_instance(request, integration_instance_id):
    user = request.user
    integration_instance = get_object_or_404(
        IntegrationInstance, pk=integration_instance_id
    )
    assert integration_instance.metric.user == user  # TODO: AUTH instead
    measurement = collect(integration_instance.name)
    measurement.metric = integration_instance.metric
    measurement.save()
    return HttpResponse(measurement)
