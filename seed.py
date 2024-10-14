from mainapp.models import Dashboard, Metric, User

admin_user = User.objects.get(username="john")
plausible_metric = Metric(
    integration_id="plausible", name="test_metric", user=admin_user
)
plausible_metric.save()
postgresql_metric = Metric(
    integration_id="postgresql", name="test_metric_sql", user=admin_user
)
postgresql_metric.save()
dashboard = Dashboard(
    slug="test_dashboard",
    is_public=False,
    name="test_dashboard",
    user=admin_user,
)
dashboard.save()
dashboard.metrics.set([plausible_metric, postgresql_metric])
