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
        self.assertEqual(spike_date, start_date + timedelta(days=LOOKBACK_DAYS - 5))

        self.metric.last_detected_spike = spike_date
        self.metric.save()

        self.assertIsNone(detected_spike(self.metric.pk))

    def test_detected_spike_with_equal_values(self):
        end_date = date.today()
        start_date = end_date - timedelta(days=100)
        for i in range(99):
            Measurement.objects.create(
                date=end_date - timedelta(days=i + 1),
                value=10 if i == 0 else 0,
                metric=self.metric,
            )

        spike_date = detected_spike(self.metric.pk)
        self.assertEqual(spike_date, end_date - timedelta(days=1))
        self.metric.last_detected_spike = spike_date
        self.metric.save()

        # Check that we don't re-detect the same spike
        Measurement.objects.create(
            date=end_date,
            value=10,
            metric=self.metric,
        )
        self.assertIsNone(detected_spike(self.metric.pk))

    def test_signal_with_low_std(self):
        Measurement.objects.create(
            date=date(2025, 3, 26), value=165, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 3, 27), value=165, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 3, 28), value=165, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 3, 29), value=165, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 3, 30), value=165, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 3, 31), value=351, metric=self.metric
        )
        Measurement.objects.create(date=date(2025, 4, 1), value=351, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 2), value=351, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 3), value=351, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 4), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 5), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 6), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 7), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 8), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 4, 9), value=353, metric=self.metric)
        Measurement.objects.create(
            date=date(2025, 4, 10), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 11), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 12), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 13), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 14), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 15), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 16), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 17), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 18), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 19), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 20), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 21), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 22), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 23), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 24), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 25), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 26), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 27), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 28), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 29), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 4, 30), value=353, metric=self.metric
        )
        Measurement.objects.create(date=date(2025, 5, 1), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 2), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 3), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 4), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 5), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 6), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 7), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 8), value=353, metric=self.metric)
        Measurement.objects.create(date=date(2025, 5, 9), value=353, metric=self.metric)
        Measurement.objects.create(
            date=date(2025, 5, 10), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 11), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 12), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 13), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 14), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 15), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 16), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 17), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 18), value=353, metric=self.metric
        )
        Measurement.objects.create(
            date=date(2025, 5, 19), value=354, metric=self.metric
        )
        spike_date = detected_spike(self.metric.pk)
        self.assertEqual(spike_date, None)
