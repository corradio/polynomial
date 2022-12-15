from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "integrationinstance/<int:integration_instance_id>/",
        views.integration_instance,
        name="integration_instance",
    ),
]
