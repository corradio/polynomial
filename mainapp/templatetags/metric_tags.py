from django import template

from ..models import Metric, User

register = template.Library()


@register.filter
def can_edit(metric: Metric, user: User):
    return metric.can_edit(user)


@register.filter
def can_alter_credentials_by(metric: Metric, user: User):
    return metric.can_alter_credentials_by(user)
