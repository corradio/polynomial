from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("metrics/", views.MetricListView.as_view(), name="metrics"),
    path(
        "metrics/<int:pk>/",
        views.MetricUpdateView.as_view(),
        name="metric-details",
    ),
    path(
        "metrics/add/<integration_id>/",
        views.MetricCreateView.as_view(),
        name="metric-add",
    ),
    path(
        "integrations/",
        views.IntegrationListView.as_view(),
        name="integrations",
    ),
    # TODO: Cleanup after this mark
    path(
        "metrics/<int:metric_id>/collect",
        views.metric_collect,
        name="metric_collect",
    ),
]
