from django.forms import ModelForm

from mainapp.models import IntegrationInstance


class IntegrationInstanceForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # manually set the current instance on the widget
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        self.fields["config"].widget.instance = self.instance

    class Meta:
        model = IntegrationInstance
        fields = ["integration_id", "metric", "config", "secrets"]
