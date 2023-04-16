from django import forms
from django.contrib import admin

from . import models


class MetricAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If the follow line is enabled, and if the `widget.config`
        # setting is removed from Meta, then the custom schema will be used,
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        # self.fields["integration_config"].widget.instance = self.instance

    class Meta:
        model = models.Metric
        fields = "__all__"
        # The following can be enabled in order to make the field editable as
        # normal JSON
        widgets = {"integration_config": forms.Textarea()}


class MetricAdmin(admin.ModelAdmin):
    form = MetricAdminForm


admin.site.register(models.User)
admin.site.register(models.Metric, MetricAdmin)
admin.site.register(models.Measurement)
admin.site.register(models.Dashboard)
admin.site.register(models.Organization)
admin.site.register(models.OrganizationUser)
admin.site.register(models.OrganizationInvitation)
