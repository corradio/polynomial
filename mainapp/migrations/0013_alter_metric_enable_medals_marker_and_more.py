# Generated by Django 5.0 on 2024-02-24 08:20

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0012_metric_enable_medals_metric_higher_is_better_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="metric",
            name="enable_medals",
            field=models.BooleanField(
                default=True, help_text="Highlight the top 3 values"
            ),
        ),
        migrations.CreateModel(
            name="Marker",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("date", models.DateField()),
                ("text", models.CharField(max_length=128)),
                (
                    "metric",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="mainapp.metric"
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="marker",
            constraint=models.UniqueConstraint(
                fields=("metric", "date"), name="unique_marker"
            ),
        ),
    ]
