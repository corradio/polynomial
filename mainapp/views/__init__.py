import json
import secrets
import sys
import traceback
from datetime import date, datetime, timedelta
from types import MethodType
from typing import Any, Dict, List, Optional, Union

from allauth.account.adapter import get_adapter
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.forms.models import model_to_dict
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_date, parse_duration
from django.utils.http import urlencode
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)
from django.views.generic.detail import SingleObjectMixin

from config.settings import DEBUG
from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.base import WebAuthIntegration

from .. import google_spreadsheet_export
from ..forms import MetricForm, OrganizationForm, OrganizationUserCreateForm
from ..models import (
    Dashboard,
    Measurement,
    Metric,
    Organization,
    OrganizationInvitation,
    OrganizationUser,
    User,
)
from ..tasks import backfill_task

# Re-export
from . import dashboard, metric, organization
from .utils import add_next


@login_required
def index(request):
    user = request.user
    organizations = Organization.objects.filter(users=user)
    dashboard = (
        Dashboard.objects.all()
        .filter(Q(user=user) | Q(organization__in=organizations))
        .order_by("name")
    ).first()
    if dashboard:
        return redirect(dashboard.get_absolute_url())

    return render(request, "mainapp/index.html", {})


class IntegrationListView(ListView):
    # this page should be unprotected for SEO purposes
    template_name = "mainapp/integration_list.html"

    def get_queryset(self):
        return [
            i
            for i in INTEGRATION_IDS
            if DEBUG or not INTEGRATION_CLASSES[i]._exclude_in_prod
        ]


class AuthorizeCallbackView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        state = self.request.GET["state"]
        if state not in self.request.session:
            return HttpResponseBadRequest()
        else:
            cache_obj = self.request.session[state]
            # The cache object can have either:
            # - a metric_id (if it was called from /metrics/<pk>/authorize)
            # - an organization id (if it was called from /organizations/<pk>/edit)
            # - Nothing (if it was called from /metrics/new/<state>/authorize)
            if "organization_id" in cache_obj:
                return redirect(
                    add_next(
                        google_spreadsheet_export.process_authorize_callback(
                            organization_id=cache_obj["organization_id"],
                            uri=request.build_absolute_uri(request.get_full_path()),
                            authorize_callback_uri=request.build_absolute_uri(
                                reverse("authorize-callback")
                            ),
                            state=state,
                        ),
                        next=cache_obj.get("next"),
                    )
                )

            metric = None
            if "metric_id" in cache_obj:
                # Get integration instance
                metric = get_object_or_404(
                    Metric, pk=cache_obj["metric_id"], user=request.user
                )
            integration_id = (
                metric.integration_id
                if metric
                else cache_obj["metric"]["integration_id"]
            )
            integration_class = INTEGRATION_CLASSES[integration_id]
            assert issubclass(integration_class, WebAuthIntegration)
            integration_credentials = integration_class.process_callback(
                uri=request.build_absolute_uri(request.get_full_path()),
                state=state,
                authorize_callback_uri=request.build_absolute_uri(
                    reverse("authorize-callback")
                ),
                code_verifier=cache_obj.get("code_verifier"),
            )
            # Save credentials
            if metric:
                metric.integration_credentials = integration_credentials
                metric.save()
                # Clean up session as it won't be used anymore
                del self.request.session[state]
                return redirect(
                    add_next(metric.get_absolute_url(), next=cache_obj.get("next"))
                )
            else:
                cache_obj["metric"]["integration_credentials"] = integration_credentials
                request.session.modified = True
                return redirect(
                    add_next(
                        reverse("metric-new-with-state", args=[state]),
                        next=cache_obj.get("next"),
                    )
                )


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
                f"{reverse('account_signup')}?{urlencode({'next': request.path})}"
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
                # Accept invitation
                invitation.accept(request.user)
                # Send notification to invitee
                ctx = {"invitation": invitation}
                email_template = "mainapp/email/organizationinvitation_accepted"
                get_adapter().send_mail(email_template, invitation.inviter.email, ctx)
                return redirect("organization_list")
            else:
                raise PermissionDenied(
                    "This invitation is not valid for emails associated with this account."
                )
