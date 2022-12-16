from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "integrationinstance/<int:integration_instance_id>/",
        views.integration_instance,
        name="integration_instance",
    ),
    path(
        "integrationinstance/<int:integration_instance_id>/collect",
        views.integration_instance_collect,
        name="integration_instance_collect",
    ),
]
