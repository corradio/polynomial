from mainapp.models import Metric, User

admin_user = User.objects.get(username="admin")
Metric(integration_id="plausible", name="test_metric", user=admin_user).save()
Metric(integration_id="postgresql", name="test_metric_sql", user=admin_user).save()
