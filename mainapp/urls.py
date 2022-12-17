from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("metrics/", views.MetricListView.as_view(), name="metrics"),
    path(
        "metrics/<int:metric_id>/",
        views.metric_details,
        name="metric-details",
    ),
    path(
        "metrics/<int:metric_id>/collect",
        views.metric_collect,
        name="metric_collect",
    ),
]
