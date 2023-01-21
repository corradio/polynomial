import socket
from datetime import date, timedelta
from pprint import pformat

from celery import shared_task
from celery.signals import task_failure
from celery.utils.log import get_task_logger
from django.core.mail import mail_admins
from django.forms.models import model_to_dict

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


@task_failure.connect()
def celery_task_failure_email(sender, *args, **kwargs):
    """celery 4.0 onward has no method to send emails on failed tasks
    so this event handler is intended to replace it
    """
    extras = {}

    if sender == collect_latest_task:
        metric_pk = kwargs["args"][0]
        metric = Metric.objects.get(pk=metric_pk)
        extras = model_to_dict(metric)

    subject = "[Django][{queue_name}@{host}] Error: Task {sender.name} ({task_id}): {exception}".format(
        queue_name="celery",  # `sender.queue` doesn't exist in 4.1?
        host=socket.gethostname(),
        sender=sender,
        **kwargs
    )

    message = """Task {sender.name} with id {task_id} raised exception:
{exception!r}

args = {args}
kwargs = {kwargs}

extras = {extras}

The contents of the full traceback was:

{einfo}
    """.format(
        sender=sender, extras=pformat(extras), *args, **kwargs
    )

    mail_admins(subject, message)
