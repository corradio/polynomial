import json
import socket
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from pprint import pformat
from typing import Optional, Union

import requests
from celery import shared_task
from celery.signals import task_failure
from django.core.mail import EmailMultiAlternatives, mail_admins, send_mail
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_duration
from oauthlib import oauth2
from requests.exceptions import RequestException

from config.settings import CSRF_TRUSTED_ORIGINS
from integrations.base import UserFixableError

from ..models import Measurement, Metric, Organization
from ..utils import charts
from . import metric_analyse
from .google_spreadsheet_export import spreadsheet_export

BASE_URL = CSRF_TRUSTED_ORIGINS[0]


@shared_task(max_retries=5, autoretry_for=(RequestException,), retry_backoff=10)
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
                measurements_iterator = inst.collect_past_range(
                    date_start=min(last_measurement.date + timedelta(days=1), date_end),
                    date_end=date_end,
                )
                for measurement in measurements_iterator:
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

    # Check notify
    check_notify_metric_update_task.delay(metric_id)


@shared_task()
def collect_all_latest_task():
    for metric in Metric.objects.all():
        collect_latest_task.delay(metric.id)
        verify_inactive_task.delay(metric.id)


@shared_task(max_retries=5, autoretry_for=(RequestException,), retry_backoff=10)
def backfill_task(metric_id: int, since: Optional[str]):
    metric = Metric.objects.get(pk=metric_id)
    if not since:
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
    # Backfill assumes no previous data is present when it was first run
    #  and will thus resume from the earliest of last collected data or start date
    #  to ensure we have full data coverage
    last_measurement = (
        Measurement.objects.filter(metric=metric_id).order_by("-date").first()
    )
    last_measurement_date = last_measurement.date if last_measurement else date.max
    with metric.integration_instance as inst:
        measurements_iterator = inst.collect_past_range(
            date_start=max(
                min(last_measurement_date, start_date), inst.earliest_backfill()
            ),
            date_end=date.today() - timedelta(days=1),
        )
        # Save
        for measurement in measurements_iterator:
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


@shared_task
def check_notify_metric_update_task(metric_id: int):
    metric = Metric.objects.get(pk=metric_id)
    if metric_analyse.detected_spike(metric.pk):
        message = EmailMultiAlternatives(
            subject=f'New changes in metric "{metric.name}" 📈',
            body=f"Go check it out. Unfortunately can't link here as we're not sure there's a dashboard.",
            # {BASE_URL}{metric.dashboards.first?.get_absolute_url()}
            from_email="Polynomial <olivier@polynomial.so>",
            # to=[metric.user.email],
            to=["olivier.corradi@gmail.com"],
        )
        message.mixed_subtype = "related"
        message.attach_alternative(
            f"""
<h1>{metric.name}</h1>
<p>
    <img src="cid:chart" width="640", height="280" alt="chart">
</p>
""",
            "text/html",
        )
        img_data = charts.generate_png(charts.metric_chart_vl_spec(metric_id))
        image = MIMEImage(img_data)
        image.add_header("Content-Id", "<chart>")
        message.attach(image)
        message.send()


@shared_task
def verify_inactive_task(metric_id: int):
    metric = Metric.objects.get(pk=metric_id)
    # How long since last successful collect?
    last_non_nan_measurement = (
        Measurement.objects.exclude(value=float("nan"))
        .filter(metric=metric_id)
        .order_by("updated_at")
        .last()
    )
    if last_non_nan_measurement:
        # Reminder after a week
        for reminder_days in [15, 30, 90]:
            if (
                datetime.now(timezone.utc) - last_non_nan_measurement.updated_at
            ).days == reminder_days:
                # On the nth day, send out a reminder
                message = f"""Hello {metric.user.first_name} 👋

It seems like your metric "{metric.name}" hasn't collected any new data in the last {reminder_days}.

To fix this error, you might have to reconfigure your metric by following the link below:
{BASE_URL}{reverse('metric-details', args=[metric_id])}
    """
                send_mail(
                    subject=f"Your metric {metric.name} hasn't collected new data in {reminder_days} days",
                    message=message,
                    from_email="Polynomial <olivier@polynomial.so>",
                    recipient_list=[metric.user.email],
                )


@task_failure.connect()
def celery_task_failure_email(sender, *args, **kwargs):
    exception = kwargs["exception"]
    subject = None
    message = ""

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
        elif isinstance(exception, (UserFixableError, requests.HTTPError)):
            # If it's an HTTPError, only handle certain error codes
            # - 401 Unauthorized: client provides no credentials or invalid credentials
            # - 403 Forbidden: has valid credentials but not enough privileges
            if not isinstance(
                exception, requests.HTTPError
            ) or exception.response.status_code in [400, 401, 403]:
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
        if subject and message:
            return send_mail(
                subject,
                message,
                from_email="Polynomial <olivier@polynomial.so>",
                recipient_list=[metric.user.email],
            )

    # Generic handler
    extras = {}

    # Add some details if this is a HTTPError
    if isinstance(exception, requests.HTTPError):
        try:
            extras["response_json"] = exception.response.json()
        except json.decoder.JSONDecodeError:
            pass

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
