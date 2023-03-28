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
from .mixins import (
    OrganizationAdminRequiredMixin,
    OrganizationMembershipRequiredMixin,
    OrganizationOwnerRequiredMixin,
    OrganizationUserMixin,
)


class OrganizationListView(LoginRequiredMixin, ListView):
    model = Organization

    def get_queryset(self):
        assert isinstance(self.request.user, User)
        return Organization.objects.filter(users=self.request.user)


class OrganizationCreateView(LoginRequiredMixin, CreateView):
    model = Organization
    form_class = OrganizationForm
    success_url = reverse_lazy("organization_list")

    def get_initial(self):
        return {"owner": self.request.user}


class OrganizationUpdateView(
    LoginRequiredMixin, OrganizationAdminRequiredMixin, UpdateView
):
    model = Organization
    pk_url_kwarg = "organization_pk"
    form_class = OrganizationForm


class OrganizationDeleteView(
    LoginRequiredMixin, OrganizationOwnerRequiredMixin, DeleteView
):
    object: Organization
    model = Organization
    pk_url_kwarg = "organization_pk"
    success_url = reverse_lazy("organization_list")


class OrganizationUserListView(
    LoginRequiredMixin, OrganizationMembershipRequiredMixin, ListView
):
    model = OrganizationUser

    def get_queryset(self):
        return OrganizationUser.objects.filter(
            organization=self.kwargs["organization_pk"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = Organization.objects.get(
            pk=self.kwargs["organization_pk"]
        )
        context["is_organization_admin"] = context["organization"].is_admin(
            self.request.user
        )
        return context


class OrganizationUserCreateView(
    LoginRequiredMixin, OrganizationAdminRequiredMixin, CreateView
):
    model = OrganizationUser
    form_class = OrganizationUserCreateForm

    def get_success_url(self):
        return reverse(
            "organization_user_list",
            kwargs={"organization_pk": self.kwargs["organization_pk"]},
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = Organization.objects.get(
            pk=self.kwargs["organization_pk"]
        )
        return context

    def get_initial(self):
        return {"inviter": self.request.user}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(
            {"request": self.request, "organization_pk": self.kwargs["organization_pk"]}
        )
        return kwargs


class OrganizationUserDeleteView(
    LoginRequiredMixin,
    OrganizationAdminRequiredMixin,
    OrganizationUserMixin,
    DeleteView,
):
    object: OrganizationUser
    model = OrganizationUser

    def get_success_url(self):
        return reverse(
            "organization_user_list",
            kwargs={"organization_pk": self.object.organization.pk},
        )


@login_required
def authorize_google_spreadsheet_export(request: HttpRequest, organization_pk: int):
    organization = get_object_or_404(Organization, pk=organization_pk)
    if not organization.is_admin(request.user):
        return HttpResponseNotFound()
    uri, state = google_spreadsheet_export.authorize(request)
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        "organization_id": organization.id,
    }
    return HttpResponseRedirect(uri)
