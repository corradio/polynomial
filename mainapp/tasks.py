import socket
from datetime import date, timedelta
from pprint import pformat
from typing import Optional

from celery import shared_task
from celery.signals import task_failure
from celery.utils.log import get_task_logger
from django.core.mail import mail_admins
from django.forms.models import model_to_dict
from django.utils.dateparse import parse_date, parse_duration

from .models import Measurement, Metric

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


@task_failure.connect()
def celery_task_failure_email(sender, *args, **kwargs):
    extras = {}

    if sender == collect_latest_task:
        metric_pk = kwargs["args"][0]
        metric = Metric.objects.get(pk=metric_pk)
        extras = {"metric": model_to_dict(metric)}

    subject = "[{queue_name}@{host}] Error: {exception}:".format(
        queue_name="celery",  # `sender.queue` doesn't exist in 4.1?
        host=socket.gethostname(),
        **kwargs,
    )

    message = """{exception!r}

Traceback:

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
