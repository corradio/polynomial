import socket
from datetime import date, datetime, timedelta
from pprint import pformat
from typing import Optional, Union

import requests
from celery import shared_task
from celery.signals import task_failure
from celery.utils.log import get_task_logger
from django.core.mail import mail_admins, send_mail
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_duration
from oauthlib import oauth2

from config.settings import CSRF_TRUSTED_ORIGINS
from integrations.base import UserFixableError

from .google_spreadsheet_export import spreadsheet_export
from .models import Measurement, Metric, Organization

BASE_URL = CSRF_TRUSTED_ORIGINS[0]

logger = get_task_logger(__name__)


@shared_task()
def collect_latest_task(metric_id: int):
    metric = Metric.objects.get(pk=metric_id)
    integration_instance = metric.integration_instance
    if integration_instance.can_backfill():
        # Check if we should gather previously missing datapoints
        # by getting last measurement
        last_measurement = (
            Measurement.objects.filter(metric=metric_id).order_by("-date").first()
        )
        if last_measurement:
            with integration_instance as inst:
                date_end = date.today() - timedelta(days=1)
                measurements = inst.collect_past_range(
                    date_start=min(last_measurement.date + timedelta(days=1), date_end),
                    date_end=date_end,
                )
            for measurement in measurements:
                Measurement.objects.update_or_create(
                    metric=metric,
                    date=measurement.date,
                    defaults={
                        "value": measurement.value,
                    },
                )
            return

    # For integration that can't backfill
    with integration_instance as inst:
        measurement = inst.collect_latest()
    Measurement.objects.update_or_create(
        metric=metric,
        date=measurement.date,
        defaults={
            "value": measurement.value,
        },
    )


@shared_task()
def collect_all_latest_task():
    for metric in Metric.objects.all():
        collect_latest_task.delay(metric.id)


@shared_task()
def backfill_task(metric_id: int, since: Optional[str]):
    metric = Metric.objects.get(pk=metric_id)
    if since is None:
        start_date: Optional[date] = date.min
    else:
        start_date = parse_date(since)
        if not start_date:
            interval = parse_duration(since)  # e.g. "3 days"
            if not interval:
                raise ValueError(
                    f"Invalid argument `since`: should be a date or a duration."
                )
            start_date = date.today() - interval
    assert start_date is not None
    with metric.integration_instance as inst:
        measurements = inst.collect_past_range(
            date_start=max(start_date, inst.earliest_backfill()),
            date_end=date.today() - timedelta(days=1),
        )
    logger.info(f"Collected {len(measurements)} measurements")
    # Save
    for measurement in measurements:
        Measurement.objects.update_or_create(
            metric=metric,
            date=measurement.date,
            defaults={
                "value": measurement.value,
                "metric": metric,
            },
        )


@shared_task
def spreadsheet_export_all():
    required_fields = [
        "google_spreadsheet_export_spreadsheet_id",
        "google_spreadsheet_export_credentials",
        "google_spreadsheet_export_sheet_name",
    ]
    for organization in Organization.objects.filter(
        **{f"{f}__isnull": False for f in required_fields}
    ):
        spreadsheet_export.delay(
            organization_id=organization.pk,
        )


@task_failure.connect()
def celery_task_failure_email(sender, *args, **kwargs):
    exception = kwargs["exception"]

    if sender == collect_latest_task:
        metric_pk = kwargs["args"][0]
        metric = Metric.objects.get(pk=metric_pk)
        extras = {"metric": model_to_dict(metric)}

        if isinstance(exception, oauth2.rfc6749.errors.InvalidGrantError):
            # Handler for expired OAuth
            subject = f"Aw snap, collecting data for the {metric.name} metric failed 😟"
            message = f"""Hello {metric.user.first_name} 👋

Unfortunately, something went wrong last night when attempting to collect the latest data for the {metric.name} metric.
It seems like the authorization expired.

To fix the error, you will have to re-authorize by following the link below:
{BASE_URL}{reverse('metric-authorize', args=[metric_pk])}
"""
        elif isinstance(exception, UserFixableError) or isinstance(
            exception, requests.HTTPError
        ):
            # If it's an HTTPError, only handle 400 and 403
            if not isinstance(
                exception, requests.HTTPError
            ) or exception.response.status_code in [400, 403]:
                # Handler for exceptions that can be fixed by the user
                subject = (
                    f"Aw snap, collecting data for the {metric.name} metric failed 😟"
                )
                message = f"""Hello {metric.user.first_name} 👋

Unfortunately, something went wrong last night when attempting to collect the latest data for the {metric.name} metric.
The error was: {exception}

To fix this error, you might have to reconfigure your metric by following the link below:
{BASE_URL}{reverse('metric-details', args=[metric_pk])}
"""
        return send_mail(
            subject,
            message,
            from_email="olivier@polynomial.so",
            recipient_list=[metric.user.email],
        )

    # Generic handler
    extras = {}

    subject = "[{queue_name}@{host}] Error: {exception}:".format(
        queue_name="celery",  # `sender.queue` doesn't exist in 4.1?
        host=socket.gethostname(),
        **kwargs,
    )

    message = """{exception!r}

{einfo}

task = {sender.name}
task_id = {task_id}
args = {args}
kwargs = {kwargs}

extras = {extras}
    """.format(
        sender=sender, extras=pformat(extras), *args, **kwargs
    )

    mail_admins(subject, message)
