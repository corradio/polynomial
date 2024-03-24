from django.test import TestCase

from . import Dashboard, Metric, Organization, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user1 = User.objects.create(username="user1")
        self.user2 = User.objects.create(username="user2")
        self.org1 = Organization.create(name="org1", owner=self.user1)
        # User 1 is not in org
        self.org1.add_user(self.user2)
        # Metric is in org (through user2)
        self.metric1 = Metric.objects.create(
            name="metric1", user=self.user2, organization=self.org1
        )
        # Dash is in org with metric
        self.dash1 = Dashboard.objects.create(
            user=self.user2, name="dash1", organization=self.org1
        )
        self.dash1.metrics.add(self.metric1)

        # Dummy org, dashboard and metric (for control purposes)
        self.dummy_org = Organization.create(name="dummy_org", owner=self.user1)
        self.dummy_dash = Dashboard.objects.create(
            user=self.user2, name="dummy_dash", organization=self.dummy_org
        )
        self.dummy_metric = Metric.objects.create(
            name="dummy_metric", user=self.user2, organization=self.dummy_org
        )

        self.assertTrue(
            self.dash1.can_view(self.user1),
            "Dashboard should be visible by other org user",
        )
        self.assertTrue(
            self.metric1.can_view(self.user1),
            "Metric should be visible by other org user",
        )

    def test_remove_user_from_org(self):
        """Removing a user from an org should make all of its dashboards and metrics unavailable"""

        # Remove user2 from org
        self.org1.remove_user(self.user2)

        # Check that user2 dashboard is now hidden from other org user
        self.dash1.refresh_from_db()
        self.assertFalse(
            self.dash1.can_view(self.user1),
            "Dashboard should not be visible anymore by other org user",
        )

        # Check that user2 metrics are now hidden from other org user
        self.metric1.refresh_from_db()
        self.assertFalse(
            self.metric1.can_view(self.user1),
            "Metric should not be visible anymore by other org user",
        )

        # Check that user2 dummy dashboard is still in dummy org
        self.dummy_dash.refresh_from_db()
        self.assertEqual(
            self.dummy_dash.organization,
            self.dummy_org,
            "Dummy dashboard should still belong to dummy org",
        )
        self.dummy_metric.refresh_from_db()
        self.assertEqual(
            self.dummy_metric.organization,
            self.dummy_org,
            "Dummy metric should still belong to dummy org",
        )
