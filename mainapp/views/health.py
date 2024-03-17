from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone

from ..models import Metric


def health(request):
    last_attempted_metric = (
        Metric.objects.filter(last_collect_attempt__isnull=False)
        .order_by("-last_collect_attempt")
        .first()
    )
    if not last_attempted_metric:
        return HttpResponse(status=200, content="ok (but no metric to monitor)")
    delta = timezone.now() - last_attempted_metric.last_collect_attempt
    if delta > timedelta(days=1):
        return HttpResponse(
            status=500, content=f"error: haven't attempted a collect in {delta}"
        )
    return HttpResponse(status=200, content="ok")
