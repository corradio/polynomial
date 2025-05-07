from django.test import TestCase

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

    def test_get_viewable_metrics(self):
        self.assertIn(self.metric1, self.user2.get_viewable_metrics())
