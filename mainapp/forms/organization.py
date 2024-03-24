import uuid

from allauth.account.adapter import get_adapter
from django import forms
from django.urls import reverse

from mainapp.models import Organization, OrganizationInvitation, OrganizationUser, User
from mainapp.tasks import slack_notifications

from .base import BaseModelForm


class OrganizationForm(BaseModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.google_spreadsheet_export_credentials:
            self.fields[
                "google_spreadsheet_export_spreadsheet_id"
            ].widget = forms.HiddenInput()
            self.fields[
                "google_spreadsheet_export_sheet_name"
            ].widget = forms.HiddenInput()
        if self.instance.slack_notifications_credentials:
            self.fields["slack_notifications_channel"].widget = forms.Select(
                choices=(
                    (k, k)
                    for k in slack_notifications.list_public_channels(
                        self.instance.slack_notifications_credentials
                    )
                )
            )
        else:
            self.fields["slack_notifications_channel"].widget = forms.HiddenInput()

    def save(self, commit=True):
        if not self.instance.pk:
            # This is a CreateForm
            return Organization.create(**self.cleaned_data)
        else:
            return super().save(commit)

    class Meta:
        model = Organization
        fields = [
            "name",
            "owner",
            "slug",
            "google_spreadsheet_export_spreadsheet_id",
            "google_spreadsheet_export_sheet_name",
            "slack_notifications_channel",
        ]

        widgets = {
            # Make this field available to the form but invisible to user
            "owner": forms.HiddenInput(),
        }


class OrganizationUserCreateForm(BaseModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        self.organization_pk = kwargs.pop("organization_pk")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        invitee_email = self.cleaned_data["invitee_email"]
        # Check if user is already member of organization
        try:
            invitee = User.get_by_email(invitee_email, only_verified=False)
            try:
                org_user = OrganizationUser.objects.get(
                    user=invitee, organization_id=self.organization_pk
                )
                raise forms.ValidationError("User is already part of organization")
            except OrganizationUser.DoesNotExist:
                pass
        except User.DoesNotExist:
            # We disable invitations for new users for now,
            # unless you're a Polynomial admin
            if not self.request.user.is_staff:
                forms.ValidationError("User is not already a Polynomial user.")
            else:
                pass

        # Check if user has already been invited
        try:
            invitation = OrganizationInvitation.objects.get(
                invitee_email=invitee_email,
                organization_id=self.organization_pk,
                user=None,
            )
            raise forms.ValidationError("User is already invited")
        except OrganizationInvitation.DoesNotExist:
            pass
        return cleaned_data

    def save(self, *args, **kwargs):
        invitee_email = self.cleaned_data["invitee_email"]
        try:
            invitee = User.get_by_email(invitee_email, only_verified=False)
        except User.DoesNotExist:
            # User does not exist, will have to be created when signing up
            invitee = None
        invitation = OrganizationInvitation.objects.create(
            user=invitee,  # in case user already exists
            invitation_key=uuid.uuid4(),
            invitee_email=invitee_email,
            inviter=self.request.user,
            # configuration
            is_admin=self.cleaned_data["is_admin"],
            organization_id=self.organization_pk,
        )

        # Send invitation
        invite_url = self.request.build_absolute_uri(
            reverse("invitation_accept", args=[invitation.invitation_key])
        )
        ctx = {
            "invitation": invitation,
            "invite_url": invite_url,
        }
        email_template = "mainapp/email/organizationinvitation_invite"
        get_adapter().send_mail(email_template, invitee_email, ctx)

        return invitation

    class Meta:
        model = OrganizationUser
        exclude = ("user", "organization")
        widgets = {
            # Make this field available to the form but invisible to user
            "inviter": forms.HiddenInput(),
        }
        labels = {"invitee_email": "Email"}
