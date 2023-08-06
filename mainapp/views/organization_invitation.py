from allauth.account.adapter import get_adapter
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.generic import ListView, View
from django.views.generic.detail import SingleObjectMixin

from ..models import OrganizationInvitation, User


class InvitationListView(LoginRequiredMixin, ListView):
    model = OrganizationInvitation

    def get_queryset(self):
        user = self.request.user
        assert isinstance(user, User)
        return OrganizationInvitation.objects.filter(
            invitee_email__in=user.emailaddress_set.values_list("email", flat=True),
            user=None,
        )


class InvitationAcceptView(SingleObjectMixin, View):
    model = OrganizationInvitation

    def get_object(self):
        return get_object_or_404(
            OrganizationInvitation, invitation_key=self.kwargs["key"]
        )

    def get(self, request, key):
        invitation = self.get_object()

        if request.user.is_anonymous:
            # Mark this email address as verified, and head to sign up
            get_adapter().stash_verified_email(request, invitation.invitee_email)
            # Return here once we're signed up
            return redirect(
                f"{reverse('account_login')}?{urlencode({'next': request.path})}"
            )
        else:
            # User is authenticated
            try:
                invited_user = User.get_by_email(
                    invitation.invitee_email, only_verified=False
                )
            except User.DoesNotExist:
                invited_user = None
            if request.user == invited_user:
                if invitation.user is not None:
                    # This invitation has already been accepted
                    assert invitation.user == invited_user
                    return redirect("index")
                # Accept invitation
                invitation.accept(request.user)
                # Send notification to invitee
                ctx = {"invitation": invitation}
                email_template = "mainapp/email/organizationinvitation_accepted"
                get_adapter().send_mail(email_template, invitation.inviter.email, ctx)
                return redirect("index")
            else:
                raise PermissionDenied(
                    "This invitation is not valid for emails associated with this account."
                )
