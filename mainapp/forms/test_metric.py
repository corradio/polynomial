import json

from django.test import TestCase

from mainapp.forms import MetricDashboardAddForm
from mainapp.forms.metric import MetricForm
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
        self.metric = Metric.objects.create(
            name="metric",
            user=self.user,
            integration_id="postgresql",
            integration_config={
                "database_connection": {
                    "host": "x",
                    "port": 5432,
                    "dbname": "x",
                    "user": "x",
                    "password": "very_secret_password",
                },
                "sql_query_template": "x",
            },
        )

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

    def test_password_stays_intact(self):
        # Assume the POST is the initial of the rendered GET form
        post_data = MetricForm(instance=self.metric, user=self.user).initial
        # Check we didn't leak anything
        self.assertNotIn(
            "very_secret_password", json.dumps(post_data["integration_config"])
        )
        # Check the original object is still intact
        self.assertEqual(
            self.metric.integration_config["database_connection"]["password"],
            "very_secret_password",
            "Form tampered with original object",
        )
        # Check password stays intact on the backend if we don't change anything
        form = MetricForm(data=post_data, instance=self.metric, user=self.user)
        self.assertTrue(form.is_bound)
        self.assertTrue(form.is_valid())
        form.save()
        self.metric.refresh_from_db()
        self.assertEqual(
            self.metric.integration_config["database_connection"]["password"],
            "very_secret_password",
            "Password should have stayed intact",
        )
        # Check password changed if form changes it
        post_data["integration_config"]["database_connection"][
            "password"
        ] = "new_password"
        form = MetricForm(data=post_data, instance=self.metric, user=self.user)
        self.assertTrue(form.is_bound)
        self.assertTrue(form.is_valid())
        form.save()
        self.metric.refresh_from_db()
        self.assertEqual(
            self.metric.integration_config["database_connection"]["password"],
            "new_password",
            "Password should have changed",
        )
