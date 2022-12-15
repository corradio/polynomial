from django.forms import ModelForm
from django.http import HttpResponse
from django.shortcuts import render

from integrations.collector import collect
from mainapp.models import IntegrationConfig


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
