# Generated by Django 5.0.4 on 2024-04-25 07:51

import uuid

from django.db import connection, migrations


def generate_uuids(apps, schema_editor):
    # We can't import the Metric model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    Metric = apps.get_model("mainapp", "Metric")
    with connection.cursor() as cursor:
        for metric in Metric.objects.all():
            old_metric_id = metric.id
            new_metric_id = uuid.uuid4()

            cursor.execute(
                "UPDATE mainapp_metric SET id=%s WHERE id=%s",
                [str(new_metric_id), str(old_metric_id)],
            )
            # Update any related keys
            cursor.execute(
                "UPDATE mainapp_dashboard_metrics SET metric_id=%s WHERE metric_id=%s",
                [new_metric_id, old_metric_id],
            )
            cursor.execute(
                "UPDATE mainapp_measurement SET metric_id=%s WHERE metric_id=%s",
                [new_metric_id, old_metric_id],
            )
            cursor.execute(
                "UPDATE mainapp_marker SET metric_id=%s WHERE metric_id=%s",
                [new_metric_id, old_metric_id],
            )


def generate_ints(apps, schema_editor):
    Metric = apps.get_model("mainapp", "Metric")
    with connection.cursor() as cursor:
        for i, metric in enumerate(Metric.objects.all()):
            old_metric_id = metric.id
            new_metric_id = i + 1

            cursor.execute(
                "UPDATE mainapp_metric SET id=%s WHERE id=%s",
                [str(new_metric_id), str(old_metric_id)],
            )
            # # Update any related keys
            cursor.execute(
                "UPDATE mainapp_dashboard_metrics SET metric_id=%s WHERE metric_id=%s",
                [new_metric_id, old_metric_id],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0017_alter_metric_id"),
    ]

    operations = [
        migrations.RunPython(generate_uuids, generate_ints),
    ]
