from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import BadRequest, PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, TemplateView
from oauthlib.oauth2 import AccessDeniedError
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error

from config.settings import DEBUG
from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.base import WebAuthIntegration

from ..models import Metric
from ..tasks import google_spreadsheet_export, slack_notifications

# Re-export
from . import (  # noqa
    dashboard,
    health,
    marker,
    metric,
    organization,
    organization_invitation,
    user,
)
from .utils import add_next


def get_integration_ids():
    return [
        k
        for k in INTEGRATION_IDS
        if DEBUG or not INTEGRATION_CLASSES[k]._exclude_in_prod
    ]


def index(request):
    if request.user.is_authenticated:
        return redirect("dashboards")
    return render(
        request,
        "mainapp/index.html",
        {
            "integrations": [
                {"id": k, "label": INTEGRATION_CLASSES[k].get_label()}
                for k in get_integration_ids()
            ]
        },
    )


class IntegrationListView(ListView):
    # this page should be unprotected for SEO purposes
    template_name = "mainapp/integration_list.html"

    def get_queryset(self):
        return [
            {
                "id": k,
                "label": INTEGRATION_CLASSES[k].get_label(),
                "description": INTEGRATION_CLASSES[k].description,
            }
            for k in get_integration_ids()
        ]


class AuthorizeCallbackView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        state = self.request.GET["state"]
        if state not in self.request.session:
            raise BadRequest()
        else:
            cache_obj = self.request.session[state]
            # The cache object can have either:
            # - a metric_id (if it was called from /metrics/<pk>/authorize)
            # - an organization id (if it was called from /organizations/<pk>/edit)
            # - Nothing (if it was called from /metrics/new/<state>/authorize)
            if "organization_id" in cache_obj:
                service = cache_obj.get("service")
                if service == "google":
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
                elif service == "slack":
                    return redirect(
                        add_next(
                            slack_notifications.process_authorize_callback(
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
                else:
                    raise NotImplementedError(f"Unknown service '{service}'")

            metric = None
            if "metric_id" in cache_obj:
                # Get integration instance
                metric = get_object_or_404(Metric, pk=cache_obj["metric_id"])
                if not metric.can_alter_credentials_by(request.user):
                    raise PermissionDenied()
            integration_id = (
                metric.integration_id
                if metric
                else cache_obj["metric"]["integration_id"]
            )
            integration_class = INTEGRATION_CLASSES[integration_id]
            assert issubclass(integration_class, WebAuthIntegration)
            try:
                integration_credentials = integration_class.process_callback(
                    uri=request.build_absolute_uri(request.get_full_path()),
                    state=state,
                    authorize_callback_uri=request.build_absolute_uri(
                        reverse("authorize-callback")
                    ),
                    code_verifier=cache_obj.get("code_verifier"),
                )
            except (AccessDeniedError, CustomOAuth2Error) as e:
                # Add a message and redirect
                messages.error(request, f"Something went wrong: {e.description}")
                # This will show an error screen to the user
                if metric:
                    return redirect(
                        add_next(metric.get_absolute_url(), next=cache_obj.get("next"))
                    )
                else:
                    # This is a new metric being created
                    # We don't know where the user exactly came from,
                    # so redirect to next or root
                    return redirect(cache_obj.get("next") or "/")

            # Save credentials
            if metric:
                metric.integration_credentials = integration_credentials
                # Also change ownership in case someone authorized another user's
                # integration (from the same org)
                metric.user = self.request.user
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
