import json
import socket
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from pprint import pformat
from typing import Optional

import requests
from celery import shared_task
from celery.signals import task_failure
from celery.utils.log import get_task_logger
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
from . import metric_analyse, slack_notifications
from .google_spreadsheet_export import spreadsheet_export

BASE_URL = CSRF_TRUSTED_ORIGINS[0]

logger = get_task_logger(__name__)


@shared_task(max_retries=5, autoretry_for=(RequestException,), retry_backoff=10)
def collect_latest_task(metric_id: int) -> None:
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
def backfill_task(metric_id: int, since: Optional[str] = None) -> None:
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
                retry_since = (measurement.date + timedelta(days=1)).isoformat()
        except RequestException as e:
            # This will retry the task. Countdown needs to be manually set, but
            # max_retries will follow task configuration
            countdown = 10 * (2 ** (backfill_task.request.retries + 1))
            raise backfill_task.retry(
                exc=e,
                countdown=countdown,
                kwargs={"metric_id": metric_id, "since": retry_since},
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
def check_notify_metric_changed_task(metric_id: int) -> None:
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
def verify_inactive_task(metric_id: int) -> None:
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
{BASE_URL}{reverse('metric-details', args=[metric_id])}
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
            if not isinstance(exception, requests.HTTPError) or (
                exception.response is not None
                and exception.response.status_code in [400, 401, 402, 403]
            ):
                # Handler for exceptions that can be fixed by the user
                subject = (
                    f"Aw snap, collecting data for the {metric.name} metric failed 😟"
                )
                more_detail = None
                if (
                    isinstance(exception, requests.HTTPError)
                    and exception.response is not None
                ):
                    try:
                        more_detail = exception.response.json()
                    except json.decoder.JSONDecodeError:
                        pass
                message = f"""Hello {metric.user.first_name} 👋

Unfortunately, something went wrong last night when attempting to collect the latest data for the {metric.name} metric.
The error was: {exception}"""
                if more_detail:
                    message += f"\n\nAdditional information: {more_detail}"

                message += f"""

To fix this error, you might have to reconfigure your metric by following the link below:
{BASE_URL}{reverse('metric-details', args=[metric_pk])}
"""
        if subject and message:
            send_mail(
                subject,
                message,
                from_email="Polynomial <olivier@polynomial.so>",
                recipient_list=[metric.user.email],
            )
            return

    # Generic handler
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
