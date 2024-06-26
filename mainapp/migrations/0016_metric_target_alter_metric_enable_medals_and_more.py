# Generated by Django 5.0.4 on 2024-04-09 15:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0015_remove_metric_organizations_metric_organization_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="target",
            field=models.FloatField(blank=True, help_text="Target value", null=True),
        ),
        migrations.AlterField(
            model_name="metric",
            name="enable_medals",
            field=models.BooleanField(
                default=False, help_text="Highlight the top 3 values"
            ),
        ),
        migrations.AlterField(
            model_name="metric",
            name="integration_id",
            field=models.CharField(
                choices=[
                    ("github", "github"),
                    ("google_analytics", "google_analytics"),
                    ("google_bigquery", "google_bigquery"),
                    ("google_cloud_protected_api", "google_cloud_protected_api"),
                    ("google_play_store", "google_play_store"),
                    ("google_search_console", "google_search_console"),
                    ("google_sheets", "google_sheets"),
                    ("grafana", "grafana"),
                    ("linkedin", "linkedin"),
                    ("mailchimp", "mailchimp"),
                    ("pipedrive", "pipedrive"),
                    ("plausible", "plausible"),
                    ("postgresql", "postgresql"),
                    ("stripe", "stripe"),
                    ("twitter", "twitter"),
                    ("youtube", "youtube"),
                ],
                max_length=128,
            ),
        ),
    ]
