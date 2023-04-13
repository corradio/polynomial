from typing import Optional

from django import template

from ..models import Dashboard, User

register = template.Library()


@register.filter
def can_edit(dashboard: Optional[Dashboard], user: User):
    if dashboard is None:
        return False
    return dashboard.can_edit(user)


@register.filter
def can_delete(dashboard: Optional[Dashboard], user: User):
    if dashboard is None:
        return False
    return dashboard.can_delete(user)
