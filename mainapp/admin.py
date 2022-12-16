from django import forms
from django.contrib import admin

from . import models


class IntegrationInstanceAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If the follow line is enabled, and if the `widget.config`
        # setting is removed from Meta, then the custom schema will be used,
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        # self.fields["config"].widget.instance = self.instance

    class Meta:
        model = models.IntegrationInstance
        fields = "__all__"
        # The following can be enabled in order to make the field editable as
        # normal JSON
        widgets = {"config": forms.Textarea()}


class IntegrationInstanceAdmin(admin.ModelAdmin):
    form = IntegrationInstanceAdminForm


admin.site.register(models.User)
admin.site.register(models.IntegrationInstance, IntegrationInstanceAdmin)
admin.site.register(models.Measurement)
