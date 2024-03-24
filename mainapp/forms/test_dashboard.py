from django.test import TestCase

from mainapp.forms.dashboard import DashboardMetricAddForm
from mainapp.models import Dashboard, Metric, Organization, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user")
        org = Organization.create(name="org", owner=self.user, slug="org")
        self.dash = Dashboard.objects.create(
            user=self.user, name="dash", organization=org
        )
        self.metric = Metric.objects.create(name="metric", user=self.user)

    def test_metric_org_updated_after_dashboard_assign(self):
        form = DashboardMetricAddForm(
            instance=self.dash,
            user=self.user,
            data={"metrics": [self.metric.pk]},
        )
        self.assertTrue(form.is_valid())
        form.save()
        self.metric.refresh_from_db()
        self.assertEqual(
            self.metric.organization,
            self.dash.organization,
            "Adding a metric to a dashboard with an org should change its organization",
        )
