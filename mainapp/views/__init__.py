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
from . import dashboard
from .mixins import (
    OrganizationAdminRequiredMixin,
    OrganizationMembershipRequiredMixin,
    OrganizationOwnerRequiredMixin,
    OrganizationUserMixin,
)


def deserialize_list(arg: Optional[str]):
    if not arg:
        return []
    return arg.split(",")


@login_required
def index(request):
    user = request.user
    organizations = Organization.objects.filter(users=user)
    context: Dict[str, Any] = {}
    if isinstance(user, User):
        context["dashboards"] = (
            Dashboard.objects.all()
            .filter(Q(user=user) | Q(organization__in=organizations))
            .order_by("name")
        )
        context["organizations"] = organizations.order_by("name")
        context["metrics"] = (
            Metric.objects.all()
            .filter(Q(user=user) | Q(organizations__in=organizations))
            .order_by("name")
        )
    return render(request, "mainapp/index.html", context)


@login_required
def metric_backfill(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    backfill_task.delay(metric_id=pk, since=request.POST.get("since"))
    return HttpResponse(f"Task dispatched")


@login_required
def metric_collect_latest(request, pk):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    try:
        with metric.integration_instance as inst:
            measurement = inst.collect_latest()
    except Exception as e:
        exc_info = sys.exc_info()
        return HttpResponseBadRequest("\n".join(traceback.format_exception(*exc_info)))
    Measurement.objects.update_or_create(
        metric=metric,
        date=measurement.date,
        defaults={
            "value": measurement.value,
        },
    )
    return HttpResponse(f"Success!")


@login_required
def metric_new_test(request, state):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    data = json.loads(request.body)
    config = data.get("integration_config")
    config = config and json.loads(config)
    # Get server side information
    metric_cache = request.session[state]["metric"]
    integration_id = metric_cache.get("integration_id")
    integration_credentials = metric_cache.get("integration_credentials")
    integration_class = INTEGRATION_CLASSES[integration_id]
    # Save the config in the cache so a page reload keeps it
    metric_cache["integration_config"] = config
    request.session.modified = True

    def credentials_updater(arg):
        metric_cache["integration_credentials"] = arg
        request.session.modified = True

    try:
        with integration_class(
            config,
            credentials=integration_credentials,
            credentials_updater=credentials_updater,
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    "measurement": measurement,
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        if False:
            exc_info = sys.exc_info()
            error_str = "\n".join(traceback.format_exception(*exc_info))
        else:
            error_str = f"{type(e).__name__}: {str(e)}"
        return JsonResponse(
            {"error": error_str, "datetime": datetime.now(), "status": "error"}
        )


class IntegrationListView(ListView):
    # this page should be unprotected for SEO purposes
    template_name = "mainapp/integration_list.html"

    def get_queryset(self):
        return [
            i
            for i in INTEGRATION_IDS
            if DEBUG or not INTEGRATION_CLASSES[i]._exclude_in_prod
        ]


class MetricListView(LoginRequiredMixin, ListView):
    def get_queryset(self):
        # Only return metrics for integrations that actually exist
        # This is useful for developing new integrations,
        # as having data in the db without having it present on the branch
        # might crash
        return (
            Metric.objects.all()
            .filter(user=self.request.user)
            .filter(integration_id__in=INTEGRATION_IDS)
            .order_by("name")
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["INTEGRATION_CLASSES"] = INTEGRATION_CLASSES
        assert isinstance(self.request.user, User)
        context["organization_list"] = Organization.objects.filter(
            users=self.request.user
        )
        return context

    def post(self, request, *args, **kwargs):
        # Strictly speaking should be PATCH, but it's not supported
        # in html forms
        organization_to_set = deserialize_list(
            self.request.POST.get("organization-on-list")
        )
        organization_to_unset = deserialize_list(
            self.request.POST.get("organization-off-list")
        )
        for metric_id in deserialize_list(self.request.POST.get("metric_ids")):
            metric = Metric.objects.get(pk=metric_id)
            if metric.user != self.request.user:
                raise PermissionDenied
            for organization_pk in organization_to_set:
                metric.organizations.add(organization_pk)
            for organization_pk in organization_to_unset:
                metric.organizations.remove(organization_pk)

        return redirect(reverse("metrics"))


@login_required
def metric_duplicate(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    # Copy object
    metric_object = model_to_dict(metric)
    metric_object["name"] = f"Copy of {metric_object['name']}"
    metric_object["dashboards"] = [d.pk for d in metric.dashboards.all()]
    metric_object["organizations"] = [o.pk for o in metric.organizations.all()]
    del metric_object["id"]
    del metric_object["user"]

    # Generate a new state to uniquely identify this new creation
    state = secrets.token_urlsafe(32)
    request.session[state] = {
        "metric": metric_object,
        "user_id": request.user.id,
    }
    return redirect(reverse("metric-new-with-state", args=[state]))


@login_required
def metric_new(request):
    # Generate a new state to uniquely identify this new creation
    state = secrets.token_urlsafe(32)
    request.session[state] = {
        "metric": {
            "integration_id": request.GET["integration_id"],
            "dashboards": deserialize_list(request.GET.get("dashboard_ids")),
            "organizations": deserialize_list(request.GET.get("organization_ids")),
        },
        "user_id": request.user.id,
    }
    return redirect(reverse("metric-new-with-state", args=[state]))


class MetricCreateView(LoginRequiredMixin, CreateView):
    model = Metric
    form_class = MetricForm
    success_url = reverse_lazy("index")

    def dispatch(self, request, state, *args, **kwargs):
        self.state = state
        # Make sure someone with the link can't impersonate a user
        if request.session.get(self.state, {}).get("user_id") != request.user.id:
            raise PermissionDenied
        metric_data = request.session.get(self.state, {}).get("metric", {})
        self.integration_id = metric_data.get("integration_id")
        self.integration_credentials = metric_data.get("integration_credentials")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Detect whether or not we should redirect to authorize
        integration_class = INTEGRATION_CLASSES[self.integration_id]
        can_web_auth = issubclass(integration_class, WebAuthIntegration)
        if can_web_auth and not self.integration_credentials:
            return redirect(
                reverse("metric-new-with-state-authorize", args=[self.state])
            )
        else:
            return super().get(request, *args, **kwargs)

    def get_initial(self):
        data = self.request.session.get(self.state)
        if data is None:
            return redirect(reverse("metric_new", args=[self.integration_id]))
        # Restore form
        initial = data.get("metric", {"integration_id": self.integration_id})
        assert initial["integration_id"] == self.integration_id
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        # The callable schema will require an initialised instance that will get
        # passed to it.
        # Furthermore, getting the schema from the form might cause credential
        # updates. We therefore need to pass an instance of a Metric
        # object which is capable of updating the cached credentials
        kwargs["instance"] = Metric(
            # Note we have to exclude relations from initialization params
            **{
                k: v
                for (k, v) in kwargs["initial"].items()
                if k not in ["dashboards", "organizations"]
            }
        )

        def credentials_saver(metric_instance):
            metric = self.request.session[self.state]["metric"]
            metric["integration_credentials"] = metric_instance.integration_credentials
            self.request.session[self.state] = {
                **self.request.session[self.state],
                "metric": metric,
            }

        kwargs["instance"].save_credentials = MethodType(
            credentials_saver, kwargs["instance"]
        )
        return kwargs

    def form_valid(self, form):
        # This happens when the user saves the form
        # Here we build the Metric instance (`form.instance`)
        form.instance.user = self.request.user
        # Add hidden (server only) fields
        form.instance.integration_credentials = self.integration_credentials
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_web_auth"] = issubclass(
            INTEGRATION_CLASSES[self.integration_id], WebAuthIntegration
        )
        return context


@login_required
def metric_new_authorize(request, state):
    # Get session state
    metric_data = request.session[state]["metric"]
    integration_id = metric_data["integration_id"]
    # Get integration class and get the uri
    integration_class = INTEGRATION_CLASSES[integration_id]
    assert issubclass(integration_class, WebAuthIntegration)
    uri, code_verifier = integration_class.get_authorization_uri_and_code_verifier(
        state,
        authorize_callback_uri=request.build_absolute_uri(
            reverse("authorize-callback")
        ),
    )
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        **request.session[state],
        "code_verifier": code_verifier,
    }
    return HttpResponseRedirect(uri)


class MetricDeleteView(LoginRequiredMixin, DeleteView):
    object: Metric
    model = Metric
    success_url = reverse_lazy("index")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)


class MetricUpdateView(LoginRequiredMixin, UpdateView):
    model = Metric
    form_class = MetricForm
    success_url = reverse_lazy("index")

    def get_queryset(self, *args, **kwargs):
        # Only show metric if user can access it
        return super().get_queryset(*args, **kwargs).filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.object
        context["can_web_auth"] = metric.can_web_auth
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


@login_required
def metric_authorize(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    integration_id = metric.integration_id
    # Get integration class and get the uri
    integration_class = INTEGRATION_CLASSES[integration_id]
    assert issubclass(integration_class, WebAuthIntegration)
    # Generate state to uniquely identify this request
    state = secrets.token_urlsafe(32)
    uri, code_verifier = integration_class.get_authorization_uri_and_code_verifier(
        state,
        authorize_callback_uri=request.build_absolute_uri(
            reverse("authorize-callback")
        ),
    )
    assert uri is not None
    # Save parameters in session
    request.session[state] = {
        "metric_id": metric.id,
        "code_verifier": code_verifier,
    }
    return HttpResponseRedirect(uri)


@login_required
def metric_test(request, pk):
    if not request.method == "POST":
        return HttpResponseNotAllowed(["POST"])
    data = json.loads(request.body)
    config = data.get("integration_config")
    config = config and json.loads(config)
    # Get server side information
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    integration_id = metric.integration_id
    integration_credentials = metric.integration_credentials
    integration_class = INTEGRATION_CLASSES[integration_id]

    def credentials_updater(arg):
        metric.integration_credentials = arg
        metric.save()

    try:
        with integration_class(
            config,
            credentials=integration_credentials,
            credentials_updater=credentials_updater,
        ) as inst:
            measurement = inst.collect_latest()
            return JsonResponse(
                {
                    "measurement": measurement,
                    "datetime": datetime.now(),
                    "canBackfill": inst.can_backfill(),
                    "status": "ok",
                    "newSchema": inst.callable_config_schema(),
                }
            )
    except Exception as e:
        if True:
            exc_info = sys.exc_info()
            error_str = "\n".join(traceback.format_exception(*exc_info))
        else:
            error_str = f"{type(e).__name__}: {str(e)}"
        return JsonResponse(
            {"error": error_str, "datetime": datetime.now(), "status": "error"}
        )


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
                    google_spreadsheet_export.process_authorize_callback(
                        organization_id=cache_obj["organization_id"],
                        uri=request.build_absolute_uri(request.get_full_path()),
                        authorize_callback_uri=request.build_absolute_uri(
                            reverse("authorize-callback")
                        ),
                        state=state,
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
                return redirect(metric)
            else:
                cache_obj["metric"]["integration_credentials"] = integration_credentials
                request.session.modified = True
                return redirect(reverse("metric-new-with-state", args=[state]))


def page(request, username_or_org_slug):
    try:
        user = User.objects.get(username=username_or_org_slug)
        page_name = user.name
        id_query = Q(user=user)  # dashboards owned by user
    except User.DoesNotExist:
        # try org slug
        organization = get_object_or_404(Organization, slug=username_or_org_slug)
        page_name = organization.name
        id_query = Q(organization=organization)  # owned by org

    organizations = Organization.objects.filter(users=request.user)
    dashboards = Dashboard.objects.filter(
        id_query
        # to able to list it, the dashboard needs to be
        # either owned by visitor, public dashboard,
        # or visitor needs to be member of dashboard org
        & (Q(user=request.user) | Q(is_public=True) | Q(organization__in=organizations))
    )

    context = {
        "dashboards": dashboards,
        "page_name": page_name,
    }
    return render(request, "mainapp/page.html", context)


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
