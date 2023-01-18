from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "callbacks/authorize",
        views.AuthorizeCallbackView.as_view(),
        name="authorize-callback",
    ),
    # Metrics
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
        "metrics/<int:pk>/authorize",
        views.metric_authorize,
        name="metric-authorize",
    ),
    path(
        "metrics/<int:pk>/test",
        views.metric_test,
        name="metric-test",
    ),
    path(
        "metrics/<int:pk>/duplicate",
        views.metric_duplicate,
        name="metric-duplicate",
    ),
    # These are metric creation routes, which use the cache as backend
    path(
        "metrics/new",
        views.metric_new,
        name="metric-new",
    ),
    path(
        "metrics/new/<state>/",
        views.MetricCreateView.as_view(),
        name="metric-new-with-state",
    ),
    path(
        "metrics/new/<state>/authorize",
        views.metric_new_authorize,
        name="metric-new-with-state-authorize",
    ),
    path(
        "metrics/new/<state>/test",
        views.metric_new_test,
        name="metric-new-with-state-test",
    ),
    # Integrations (i.e. metric, and thus, db independent)
    path(
        "integrations/",
        views.IntegrationListView.as_view(),
        name="integrations",
    ),
]
