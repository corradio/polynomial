# Generated by Django 4.1.7 on 2023-03-08 19:22

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0008_remove_dashboard_unique_dashboard_user_slug_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="dashboards",
            field=models.ManyToManyField(blank=True, to="mainapp.dashboard"),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_spreadsheet_export_credentials",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_spreadsheet_export_sheet_name",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_spreadsheet_export_spreadsheet_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name="dashboard",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="mainapp.organization",
            ),
        ),
        migrations.AlterField(
            model_name="metric",
            name="organizations",
            field=models.ManyToManyField(blank=True, to="mainapp.organization"),
        ),
    ]
