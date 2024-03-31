from django.test import TestCase
from django.urls import reverse

from mainapp.models import Metric, User


class UnitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user")
        self.metric = Metric.objects.create(
            name="metric",
            user=self.user,
            integration_credentials={"key": "very_secret_credential"},
            integration_id="postgresql",
            integration_config={
                "database_connection": {"password": "very_secret_password"}
            },
        )
        self.client.force_login(self.user)

    def test_credential_leak(self):
        response = self.client.get(reverse("metric-details", args=(self.metric.pk,)))
        self.assertNotContains(
            response,
            "very_secret_credential",
            status_code=200,
            msg_prefix="integration_credential should not appear in form HTML",
        )

    def test_password_leak(self):
        response = self.client.get(reverse("metric-details", args=(self.metric.pk,)))
        self.assertNotContains(
            response,
            "very_secret_password",
            status_code=200,
            msg_prefix="password from integration_config should not appear in form HTML",
        )
