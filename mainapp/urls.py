from django.urls import include, path

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
        name="metric_delete",
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
        name="metric_new",
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
    # Orgs
    path(
        "orgs/",
        include(
            [
                path(
                    "",
                    views.OrganizationListView.as_view(),
                    name="organization_list",
                ),
                path(
                    "new",
                    views.OrganizationCreateView.as_view(),
                    name="organization_new",
                ),
                path(
                    "<int:organization_pk>/",
                    include(
                        [
                            path(
                                "edit",
                                views.OrganizationUpdateView.as_view(),
                                name="organization_edit",
                            ),
                            path(
                                "delete",
                                views.OrganizationDeleteView.as_view(),
                                name="organization_delete",
                            ),
                            path(
                                "orgusers/",
                                views.OrganizationUserListView.as_view(),
                                name="organization_user_list",
                            ),
                            path(
                                "orgusers/new",
                                views.OrganizationUserCreateView.as_view(),
                                name="organization_user_new",
                            ),
                            path(
                                "orgusers/<int:organization_user_pk>/delete",
                                views.OrganizationUserDeleteView.as_view(),
                                name="organization_user_delete",
                            ),
                        ]
                    ),
                ),
            ]
        ),
    ),
    # Invitations
    path(
        "invitations/",
        view=views.InvitationListView.as_view(),
        name="invitation_list",
    ),
    path(
        "invitations/<key>",
        view=views.InvitationAcceptView.as_view(),
        name="invitation_accept",
    ),
    # Dashboards
    path(
        "dashboards/",
        include(
            [
                path(
                    "new",
                    view=views.dashboard.DashboardCreateView.as_view(),
                    name="dashboard_new",
                ),
                path(
                    "<int:dashboard_pk>/delete",
                    view=views.dashboard.DashboardDeleteView.as_view(),
                    name="dashboard_delete",
                ),
                path(
                    "<int:dashboard_pk>/edit",
                    view=views.dashboard.DashboardUpdateView.as_view(),
                    name="dashboard_edit",
                ),
                path(
                    "<int:dashboard_pk>/metrics/add",
                    view=views.dashboard.DashboardMetricAddView.as_view(),
                    name="dashboardmetric_add",
                ),
                # path(
                #     "<int:dashboard_pk>/metrics/remove",
                #     view=...,
                #     name="dashboardmetric_remove",
                # ),
            ]
        ),
    ),
    # User pages
    path(
        "<username_or_org_slug>/",  # this one needs to be at the bottom
        views.page,
        name="page",
    ),
    # Dashboards
    path(
        "<username_or_org_slug>/<dashboard_slug>",  # this one needs to be at the bottom
        views.dashboard.dashboard_view,
        name="dashboard",
    ),
]
