from django import template

from ..models import Metric, User

register = template.Library()


@register.filter
def can_edit(metric: Metric, user: User):
    return metric.can_edit(user)


@register.filter
def can_delete(metric: Metric, user: User):
    return metric.can_delete(user)


@register.filter
def can_be_backfilled_by(metric: Metric, user: User):
    return metric.can_be_backfilled_by(user)


@register.filter
def can_alter_credentials_by(metric: Metric, user: User):
    return metric.can_alter_credentials_by(user)
