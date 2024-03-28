from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.views.generic.base import View
from django.views.generic.detail import SingleObjectMixin

from ..models import Organization, OrganizationUser

# This enables type-checking to know we're going to mix into a View
if TYPE_CHECKING:
    _Base = View
else:
    _Base = object


class OrganizationUserMixin(SingleObjectMixin, _Base):
    def get_object(self, queryset=None):
        organization_pk = self.kwargs["organization_pk"]
        organization_user_pk = self.kwargs.get("organization_user_pk", None)
        return get_object_or_404(
            OrganizationUser.objects.select_related(),
            pk=organization_user_pk,
            organization__pk=organization_pk,
        )


class OrganizationMembershipRequiredMixin(_Base):
    def dispatch(self, request, *args, **kwargs):
        organization = get_object_or_404(Organization, pk=kwargs["organization_pk"])
        if not organization.is_member(request.user):
            raise PermissionDenied("You don't have access to this organization")
        return super().dispatch(request, *args, **kwargs)


class OrganizationAdminRequiredMixin(_Base):
    def dispatch(self, request, *args, **kwargs):
        organization = get_object_or_404(Organization, pk=kwargs["organization_pk"])
        if not organization.is_admin(request.user):
            raise PermissionDenied(
                "You need to be an administrator of this organization"
            )
        return super().dispatch(request, *args, **kwargs)


class OrganizationOwnerRequiredMixin(_Base):
    def dispatch(self, request, *args, **kwargs):
        organization = get_object_or_404(Organization, pk=kwargs["organization_pk"])
        if organization.owner != request.user:
            raise PermissionDenied("You need to be an owner of this organization")
        return super().dispatch(request, *args, **kwargs)
