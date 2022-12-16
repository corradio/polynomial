from mainapp.models import IntegrationInstance, Metric, User

Metric(name="test_metric", user=User.objects.get(username="admin")).save()
Metric(name="test_metric_sql", user=User.objects.get(username="admin")).save()
IntegrationInstance(
    integration_id="plausible", metric=Metric.objects.get(name="test_metric")
).save()
IntegrationInstance(
    integration_id="postgresql", metric=Metric.objects.get(name="test_metric_sql")
).save()
