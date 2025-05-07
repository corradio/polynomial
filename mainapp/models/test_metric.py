from django.test import Client, TestCase

from integrations import INTEGRATION_IDS

from . import Metric, Organization, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user1 = User.objects.create(username="user1")
        self.user2 = User.objects.create(username="user2")
        self.org1 = Organization.create(name="org1", owner=self.user1)
        self.org1.add_user(self.user2, is_admin=True)
        # Add metric in org (through user1, the owner)
        self.metric1 = Metric.objects.create(
            name="metric1",
            user=self.org1.owner,
            organization=self.org1,
            integration_id=INTEGRATION_IDS[0],
        )
        self.assertIn(self.org1, self.user2.organization_users.all())

    def test_metric_editable_by_admin(self):
        self.assertTrue(
            self.metric1.can_view(self.user2),
            "Metric should be viewable by other org admin",
        )
        self.assertTrue(
            self.metric1.can_edit(self.user2),
            "Metric should be editable by other org admin",
        )

    def test_metric_in_response(self):
        c = Client()
        c.force_login(user=self.user2)
        response = c.get("/metrics/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("metric1", str(response.content))
