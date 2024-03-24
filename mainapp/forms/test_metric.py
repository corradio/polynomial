from django.test import TestCase

from mainapp.forms import MetricDashboardAddForm
from mainapp.models import Dashboard, Metric, Organization, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user")
        org1 = Organization.create(name="org1", owner=self.user, slug="org1")
        org2 = Organization.create(name="org2", owner=self.user, slug="org2")
        self.dash1 = Dashboard.objects.create(
            user=self.user, name="dash1", organization=org1
        )
        self.dash2 = Dashboard.objects.create(
            user=self.user, name="dash2", organization=org2
        )
        self.metric = Metric.objects.create(name="metric", user=self.user)

    def test_metric_in_dash_multiple_orgs(self):
        form = MetricDashboardAddForm(
            instance=self.metric,
            user=self.user,
            data={"dashboards": [self.dash1.pk, self.dash2.pk]},
        )
        self.assertFalse(
            form.is_valid(),
            "A metric should not belong to multiple organizations through dashboards",
        )

    def test_metric_org_updated_after_dashboard_assign(self):
        form = MetricDashboardAddForm(
            instance=self.metric,
            user=self.user,
            data={"dashboards": [self.dash1.pk]},
        )
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(
            self.metric.organization,
            self.dash1.organization,
            "Adding a metric to a dashboard with an org should change the metric's organization",
        )
