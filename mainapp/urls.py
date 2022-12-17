from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "metric/<int:metric_id>/",
        views.metric,
        name="metric",
    ),
    path(
        "metric/<int:metric_id>/collect",
        views.metric_collect,
        name="metric_collect",
    ),
]
