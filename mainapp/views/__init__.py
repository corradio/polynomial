from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, TemplateView

from config.settings import DEBUG
from integrations import INTEGRATION_CLASSES, INTEGRATION_IDS
from integrations.base import WebAuthIntegration

from ..models import Metric
from ..tasks import google_spreadsheet_export

# Re-export
from . import dashboard, metric, organization, organization_invitation  # noqa
from .utils import add_next


def index(request):
    if request.user.is_authenticated:
        return redirect("dashboards")
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
