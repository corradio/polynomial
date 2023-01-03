from django.forms import HiddenInput, ModelForm

from mainapp.models import Metric


class MetricForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The callable schema doesn't support getting initial values
        # (i.e. when the instance is not set yet), so we must hack our
        # way through it here.
        if kwargs.get("initial", {}).get("integration_id"):
            self.fields["integration_config"].widget.schema = self.fields[
                "integration_config"
            ].widget.schema(Metric(integration_id=kwargs["initial"]["integration_id"]))
        # manually set the current instance on the widget
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        self.fields["integration_config"].widget.instance = self.instance

    class Meta:
        model = Metric
        fields = ["name", "integration_config", "integration_id", "credentials"]
        widgets = {
            # Make this field available to the form but invisible to user
            "integration_id": HiddenInput(),
            "credentials": HiddenInput(),
        }
