from django.contrib import admin

# Register your models here.
from . import models

admin.site.register(models.User)
admin.site.register(models.IntegrationInstance)
admin.site.register(models.Metric)
admin.site.register(models.Measurement)
