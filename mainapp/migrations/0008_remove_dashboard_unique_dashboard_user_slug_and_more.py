# Generated by Django 4.1.7 on 2023-03-02 16:38

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0007_metric_organizations_alter_organizationuser_inviter"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dashboard",
            name="unique_dashboard_user_slug",
        ),
        migrations.AddField(
            model_name="dashboard",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="mainapp.organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="dashboard",
            constraint=models.UniqueConstraint(
                fields=("organization", "slug"), name="unique_dashboard_org_slug"
            ),
        ),
        migrations.AddConstraint(
            model_name="dashboard",
            constraint=models.UniqueConstraint(
                condition=models.Q(("organization__isnull", True)),
                fields=("user", "slug"),
                name="unique_dashboard_owner_slug",
            ),
        ),
    ]
