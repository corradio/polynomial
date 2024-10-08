# Generated by Django 5.0.6 on 2024-09-08 08:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0022_metric_should_backfill_daily"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="last_detected_spike",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="metric",
            name="enable_medals",
            field=models.BooleanField(
                default=False, help_text="Highlights the top 3 values in the graphs"
            ),
        ),
        migrations.AlterField(
            model_name="metric",
            name="integration_id",
            field=models.CharField(
                choices=[
                    ("facebook", "facebook"),
                    ("github", "github"),
                    ("google_analytics", "google_analytics"),
                    ("google_bigquery", "google_bigquery"),
                    ("google_cloud_protected_api", "google_cloud_protected_api"),
                    ("google_play_store", "google_play_store"),
                    ("google_search_console", "google_search_console"),
                    ("google_sheets", "google_sheets"),
                    ("grafana", "grafana"),
                    ("instagram", "instagram"),
                    ("linkedin", "linkedin"),
                    ("mailchimp", "mailchimp"),
                    ("pipedrive", "pipedrive"),
                    ("plausible", "plausible"),
                    ("postgresql", "postgresql"),
                    ("stripe", "stripe"),
                    ("threads", "threads"),
                    ("twitter", "twitter"),
                    ("youtube", "youtube"),
                ],
                max_length=128,
            ),
        ),
        migrations.AlterField(
            model_name="metric",
            name="should_backfill_daily",
            field=models.BooleanField(
                default=False,
                help_text="Does a full backfill during each daily update (experimental)",
            ),
        ),
        migrations.AlterField(
            model_name="metric",
            name="target",
            field=models.FloatField(
                blank=True,
                help_text="Displays a horizontal line on the graphs, representing the goal or target",
                null=True,
            ),
        ),
    ]
