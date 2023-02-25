from django import template

from ..models import Organization, User

register = template.Library()


@register.filter
def is_admin(org: Organization, user: User):
    return org.is_admin(user)
