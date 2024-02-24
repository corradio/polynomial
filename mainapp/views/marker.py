import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date

from ..models import Marker, Metric


@login_required
def marker_with_date(request, pk: int, marker_date_str: str):
    if not request.method in ["DELETE"]:
        return HttpResponseNotAllowed(["DELETE"])
    # Get marker
    marker = get_object_or_404(Marker, date=parse_date(marker_date_str), metric_id=pk)
    if not marker.can_edit(request.user):
        raise PermissionDenied
    # Delete marker
    marker.delete()
    return HttpResponse(status=204)


@login_required
def marker(request, pk: int):
    if not request.method in ["POST"]:
        return HttpResponseNotAllowed(["POST"])
    metric = Metric.objects.get(pk=pk)
    if not metric.can_edit(request.user):
        raise PermissionDenied
    # Parse
    body = json.loads(request.body)
    # Upsert
    marker, created = Marker.objects.update_or_create(
        # Match query
        metric=metric,
        date=parse_date(body["date"]),
        # Update
        defaults={
            "text": body["text"],
        },
    )
    if created:
        return HttpResponse(status=201)
    else:
        return HttpResponse(status=204)
