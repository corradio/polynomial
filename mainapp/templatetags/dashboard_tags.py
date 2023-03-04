from django import template

from ..models import Dashboard, User

register = template.Library()


@register.filter
def can_edit(dashboard: Dashboard, user: User):
    return dashboard.can_edit(user)


@register.filter
def can_delete(dashboard: Dashboard, user: User):
    return dashboard.can_delete(user)
