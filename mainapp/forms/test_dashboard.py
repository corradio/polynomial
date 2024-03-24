from django.test import TestCase

from mainapp.forms.dashboard import DashboardMetricAddForm
from mainapp.models import Dashboard, Metric, Organization, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user1 = User.objects.create(username="user1")
        self.user2 = User.objects.create(username="user2")
        org = Organization.create(name="org", owner=self.user1, slug="org")
        org.add_user(self.user2)
        # Dashboard belongs to org..
        self.dash = Dashboard.objects.create(
            user=self.user1, name="dash", organization=org
        )
        # ..but metric does not.
        self.metric = Metric.objects.create(name="metric", user=self.user1)

    def test_metric_org_updated_after_dashboard_assign(self):
        self.assertFalse(
            self.metric.can_view(self.user2),
            "Metric should not be visible by other org user",
        )
        form = DashboardMetricAddForm(
            instance=self.dash,
            user=self.user1,
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
        self.assertTrue(
            self.metric.can_view(self.user2),
            "Metric should now by visible by other users of the org",
        )
