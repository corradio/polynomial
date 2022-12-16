from mainapp.models import IntegrationInstance, User

admin_user = User.objects.get(username="admin")
IntegrationInstance(
    integration_id="plausible", metric_name="test_metric", user=admin_user
).save()
IntegrationInstance(
    integration_id="postgresql", metric_name="test_metric_sql", user=admin_user
).save()
