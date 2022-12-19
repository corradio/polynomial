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
        "metrics/<int:pk>/backfill",
        views.metric_backfill,
        name="metric-backfill",
    ),
    path(
        "metrics/<int:pk>/collect_latest",
        views.metric_collect_latest,
        name="metric-collect-latest",
    ),
    path(
        "metrics/<int:pk>/delete",
        views.MetricDeleteView.as_view(),
        name="metric-delete",
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
    path(
        "integrations/<integration_id>/collect_latest",
        views.integration_collect_latest,
        name="integration_collect_latest",
    ),
]
