import json

import requests
from celery.exceptions import SoftTimeLimitExceeded
from django.core.mail import send_mail
from django.forms.models import model_to_dict
from django.urls import reverse
from oauthlib import oauth2

from config.settings import CSRF_TRUSTED_ORIGINS
from integrations.base import UserFixableError

from ..models import Metric

BASE_URL = CSRF_TRUSTED_ORIGINS[0]


def notify_metric_exception(
    metric: Metric,
    friendly_context_message: str,
    exception: Exception,
    recipient_email: str,
    inlude_debug_info: bool = False,
) -> bool:
    extras = {"metric": model_to_dict(metric)}
    subject = None
    message = ""

    if isinstance(exception, SoftTimeLimitExceeded):
        # Handler for task which took too long
        subject = f"Aw snap, collecting data for the {metric.name} metric failed 😟"
        message = f"""Hello {metric.user.first_name} 👋

{friendly_context_message}
It seems like the task took too long to complete. You're welcome to try again.
"""
    elif isinstance(exception, oauth2.rfc6749.errors.InvalidGrantError):
        # Handler for expired OAuth
        subject = f"Aw snap, collecting data for the {metric.name} metric failed 😟"
        message = f"""Hello {metric.user.first_name} 👋

{friendly_context_message}
It seems like the authorization expired.

To fix the error, you will have to re-authorize by following the link below:
{BASE_URL}{reverse('metric-authorize', args=[metric.pk])}
"""
    elif isinstance(exception, (UserFixableError, requests.HTTPError)):
        # If it's an HTTPError, only handle certain error codes
        # - 401 Unauthorized: client provides no credentials or invalid credentials
        # - 403 Forbidden: has valid credentials but not enough privileges
        # - 429 Too Many Requests
        if not isinstance(exception, requests.HTTPError) or (
            exception.response is not None
            and exception.response.status_code in [400, 401, 402, 403, 429]
        ):
            # Handler for exceptions that can be fixed by the user
            subject = f"Aw snap, collecting data for the {metric.name} metric failed 😟"
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

{friendly_context_message}
The error was: {exception}"""
            if more_detail:
                message += f"\n\nAdditional information: {more_detail}"

            message += f"""

To fix this error, you might have to reconfigure your metric by following the link below:
{BASE_URL}{reverse('metric-edit', args=[metric.pk])}
"""
    if subject and message:
        send_mail(
            subject,
            message,
            from_email="Polynomial <olivier@polynomial.so>",
            recipient_list=[recipient_email],
        )
        return True

    # Unknown exception
    return False
