from datetime import date, datetime, timedelta, timezone

from django.test import TestCase

from mainapp.models.measurement import Measurement
from mainapp.models.metric import Metric
from mainapp.models.user import User
from mainapp.tasks.metric_analyse import LOOKBACK_DAYS, detected_spike


class UnitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user")
        self.metric = Metric.objects.create(
            name="metric",
            user=self.user,
            integration_id="postgresql",
        )
        self.metric.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.metric.save()

    def test_detected_spike_delayed(self):
        end_date = date.today()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)
        for i in range(LOOKBACK_DAYS - 5):
            Measurement.objects.create(
                date=start_date + timedelta(days=i), value=0, metric=self.metric
            )
        Measurement.objects.create(
            date=start_date + timedelta(days=LOOKBACK_DAYS - 5),
            value=10,
            metric=self.metric,
        )
        spike_date = detected_spike(self.metric.pk)
        self.assertIsNotNone(spike_date)

        self.metric.last_detected_spike = spike_date
        self.metric.save()

        self.assertIsNone(detected_spike(self.metric.pk))
