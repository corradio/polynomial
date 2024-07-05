import json
import socket
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from pprint import pformat
from random import random
from typing import Optional
from uuid import UUID

import requests
from celery import shared_task
from celery.signals import task_failure
from celery.utils.log import get_task_logger
from django.core.mail import EmailMultiAlternatives, mail_admins, send_mail
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_duration
from requests.exceptions import RequestException

from config.settings import CSRF_TRUSTED_ORIGINS
from mainapp.models.user import User
from mainapp.tasks.error_handling import notify_metric_exception

from ..models import Measurement, Metric, Organization
from ..utils import charts
from . import metric_analyse, slack_notifications
from .google_spreadsheet_export import spreadsheet_export

BASE_URL = CSRF_TRUSTED_ORIGINS[0]

logger = get_task_logger(__name__)


@shared_task(max_retries=5, autoretry_for=(RequestException,), retry_backoff=10)
def collect_latest_task(metric_id: UUID) -> None:
    logger.info(f"Start collect_latest_task(metric_id={metric_id})")
    metric = Metric.objects.get(pk=metric_id)

    metric.last_collect_attempt = datetime.now(timezone.utc)
    metric.save()

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
    else:
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
    logger.info(f"Will start check_notify_metric_changed_task(metric_id={metric_id})")
    check_notify_metric_changed_task.delay(metric_id)


@shared_task()
def collect_all_latest_task() -> None:
    for metric in Metric.objects.all():
        collect_latest_task.delay(metric.id)
        verify_inactive_task.delay(metric.id)


@shared_task(max_retries=10)
def backfill_task(
    requester_user_id: int,
    metric_id: UUID,
    since: Optional[str] = None,
    num_collected: float = 0,
) -> None:
    if backfill_task.request.retries:
        logger.info(
            f"Retrying backfill_task {backfill_task.request.retries}/{backfill_task.max_retries} resuming at {since}"
        )

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
        retry_since = since
        try:
            for measurement in measurements_iterator:
                Measurement.objects.update_or_create(
                    metric=metric,
                    date=measurement.date,
                    defaults={
                        "value": measurement.value,
                        "metric": metric,
                    },
                )
                num_collected += 1
                retry_since = (measurement.date + timedelta(days=1)).isoformat()
        except RequestException as e:
            # Only retry certain HTTP codes
            if e.response is None:
                raise e
            if e.response.status_code not in [429]:
                raise e
            # This will retry the task. Countdown needs to be manually set, but
            # max_retries will follow task configuration
            countdown = 10 * (2 ** (backfill_task.request.retries + 1))
            # Add some randomness as well to avoid thundering herd problem
            r = (random() - 0.5) / 5  # [-0.5, 0.5] / 5 = [-0.1, 0.1] = ±10%
            countdown *= 1 + r
            raise backfill_task.retry(
                exc=e,
                countdown=int(countdown),
                kwargs={
                    "requester_user_id": requester_user_id,
                    "metric_id": metric_id,
                    "since": retry_since,
                    "num_collected": num_collected,
                },
            )
    # Success
    requester_user = User.objects.get(pk=requester_user_id)
    message = f"""Hello {requester_user.first_name} 👋

Metric "{metric.name}" has successfully been backfilled with {num_collected} measurements.
    """
    send_mail(
        subject=f"Your metric {metric.name} has successfully been backfilled",
        message=message,
        from_email="Polynomial <olivier@polynomial.so>",
        recipient_list=[requester_user.email],
    )


@shared_task
def spreadsheet_export_all() -> None:
    required_fields = [
        "google_spreadsheet_export_spreadsheet_id",
        "google_spreadsheet_export_credentials",
        "google_spreadsheet_export_sheet_name",
    ]
    for organization in Organization.objects.filter(
        **{f"{f}__isnull": False for f in required_fields}
    ):
        logger.info(f"Scheduling organization_id={organization.pk}")
        spreadsheet_export.delay(
            organization_id=organization.pk,
        )


@shared_task
def check_notify_metric_changed_task(metric_id: UUID) -> None:
    metric = Metric.objects.get(pk=metric_id)
    spike_date = metric_analyse.detected_spike(metric.pk)
    if spike_date:
        # Send email
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
        # TODO: the following will query last measurements, which is also done
        # when calling `metric_analyse.detected_spike`
        img_data = charts.generate_png(
            charts.metric_chart_vl_spec(
                metric_id, highlight_date=spike_date, lookback_days=60
            )
        )
        image = MIMEImage(img_data)
        image.add_header("Content-Id", "<chart>")
        message.attach(image)
        message.send()
        # Check for slack messages
        organization = metric.organization
        if (
            organization
            and organization.slack_notifications_credentials
            and organization.slack_notifications_channel
        ):
            # Send slack message
            logger.info(f"Sending slack notification for metric_id={metric_id}")
            slack_notifications.notify_channel(
                organization.slack_notifications_credentials,
                organization.slack_notifications_channel,
                img_data,
                f"New changes in metric *{metric.name}*",
            )


@shared_task
def verify_inactive_task(metric_id: UUID) -> None:
    metric = Metric.objects.get(pk=metric_id)
    # How long since last successful collect?
    last_non_nan_measurement = metric.last_non_nan_measurement
    if last_non_nan_measurement:
        # Reminder after a week
        for reminder_days in [15, 30, 90]:
            if (
                datetime.now(timezone.utc) - last_non_nan_measurement.updated_at
            ).days == reminder_days:
                # On the nth day, send out a reminder
                message = f"""Hello {metric.user.first_name} 👋

It seems like your metric "{metric.name}" hasn't collected any new data in the last {reminder_days} days.

To fix this error, you might have to reconfigure your metric by following the link below:
{BASE_URL}{reverse('metric-edit', args=[metric_id])}
    """
                send_mail(
                    subject=f"Your metric {metric.name} hasn't collected new data in {reminder_days} days",
                    message=message,
                    from_email="Polynomial <olivier@polynomial.so>",
                    recipient_list=[metric.user.email],
                )


@task_failure.connect()
def celery_task_failure_email(sender, *args, **kwargs) -> None:
    exception = kwargs["exception"]
    subject = None
    message = ""

    if sender == collect_latest_task:
        metric_pk = kwargs["args"][0]
        metric = Metric.objects.get(pk=metric_pk)
        if notify_metric_exception(
            metric=metric,
            friendly_context_message=f"Unfortunately, something went wrong last night when attempting to collect the latest data for the {metric.name} metric.",
            exception=exception,
            recipient_email=metric.user.email,
        ):
            return
    elif sender == backfill_task:
        if kwargs["args"]:
            requester_user_id, metric_pk, *_ = kwargs["args"]
        else:
            requester_user_id = kwargs["kwargs"]["requester_user_id"]
            metric_pk = kwargs["kwargs"]["metric_id"]
        metric = Metric.objects.get(pk=metric_pk)
        requester_user = User.objects.get(pk=requester_user_id)
        if notify_metric_exception(
            metric=metric,
            friendly_context_message=f"Unfortunately, something went wrong when attempting to backfill the {metric.name} metric.",
            exception=exception,
            recipient_email=requester_user.email,
        ):
            return

    # Generic handler for unhandled exceptions
    extras = {}

    # Add some details if this is a HTTPError
    if isinstance(exception, requests.HTTPError) and exception.response is not None:
        try:
            extras["response_json"] = exception.response.json()
        except json.decoder.JSONDecodeError:
            pass

    queue_name = "celery"  # `sender.queue` doesn't exist in 4.1?
    host = socket.gethostname()
    subject = f"[{queue_name}@{host}] Unhandled {type(exception).__name__}"
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
