from django import template

from ..models import Metric, User

register = template.Library()


@register.filter
def can_edit(metric: Metric, user: User):
    return metric.can_edit(user)
