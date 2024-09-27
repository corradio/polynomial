from django.test import TestCase

from config.settings import DATABASES
from mainapp.models.measurement import Measurement
from mainapp.models.metric import Metric
from mainapp.models.user import User
from mainapp.tasks import collect_latest_task


class UnitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user")
        self.metric = Metric.objects.create(
            name="metric",
            user=self.user,
            integration_id="postgresql",
            integration_config={
                "database_connection": {
                    "host": DATABASES["default"]["HOST"],
                    "port": DATABASES["default"]["PORT"],
                    "dbname": DATABASES["default"]["NAME"],
                    "user": DATABASES["default"]["USER"],
                    "password": DATABASES["default"]["PASSWORD"],
                },
            },
        )

    def test_collect_latest(self):
        self.metric.integration_config = {
            **self.metric.integration_config,
            "sql_query_template": "SELECT NOW() as date, 1 as value",
        }
        self.metric.save()
        self.assertFalse(self.metric.can_backfill)

        self.assertEqual(
            Measurement.objects.filter(metric_id=self.metric.pk).count(), 0
        )
        collect_latest_task(self.metric.pk)
        self.assertGreater(
            Measurement.objects.filter(metric_id=self.metric.pk).count(), 0
        )

    def test_collect_latest_with_backfill(self):
        self.metric.integration_config = {
            **self.metric.integration_config,
            "sql_query_template": "SELECT NOW() as date, 1 as value WHERE %(date_start)s < NOW() and %(date_end)s < NOW()",
        }
        self.metric.save()
        self.assertTrue(self.metric.can_backfill)

        self.assertEqual(
            Measurement.objects.filter(metric_id=self.metric.pk).count(), 0
        )
        collect_latest_task(self.metric.pk)
        self.assertGreater(
            Measurement.objects.filter(metric_id=self.metric.pk).count(), 0
        )
