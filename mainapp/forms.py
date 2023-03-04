import uuid

from allauth.account.adapter import get_adapter
from django import forms
from django.urls import reverse

from mainapp.models import (
    Dashboard,
    Metric,
    Organization,
    OrganizationInvitation,
    OrganizationUser,
    User,
)


class MetricForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # manually set the current instance on the widget
        # see https://django-jsonform.readthedocs.io/en/latest/fields-and-widgets.html#accessing-model-instance-in-callable-schema
        self.fields["integration_config"].widget.instance = self.instance

    class Meta:
        model = Metric
        fields = ["name", "integration_config", "integration_id"]

        widgets = {
            # Make this field available to the form but invisible to user
            "integration_id": forms.HiddenInput(),
        }


class OrganizationCreateForm(forms.ModelForm):
    def save(self, commit=True):
        owner = self.cleaned_data["owner"]
        # Create the organization
        org = Organization.objects.create(**self.cleaned_data)
        # Create the owner
        OrganizationUser.objects.create(user=owner, organization=org, is_admin=True)
        # Make sure the owner is part of the members
        assert owner in org.users.all()
        return org

    class Meta:
        model = Organization
        fields = ["name", "owner", "slug"]

        widgets = {
            # Make this field available to the form but invisible to user
            "owner": forms.HiddenInput(),
        }


class OrganizationUpdateForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "owner", "slug"]

        widgets = {
            # Make this field available to the form but invisible to user
            "owner": forms.HiddenInput(),
        }


class OrganizationUserCreateForm(forms.ModelForm):
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


# class DashboardCreateForm(forms.ModelForm):
#     def save(self, commit=True):
#         owner = self.cleaned_data["owner"]
#         # Create the organization
#         org = Organization.objects.create(**self.cleaned_data)
#         # Create the owner
#         OrganizationUser.objects.create(user=owner, organization=org, is_admin=True)
#         # Make sure the owner is part of the members
#         assert owner in org.users.all()
#         return org

#     class Meta:
#         model = Organization
#         fields = ["name", "owner", "slug"]

#         widgets = {
#             # Make this field available to the form but invisible to user
#             "owner": forms.HiddenInput(),
#         }


class DashboardUpdateForm(forms.ModelForm):
    class Meta:
        model = Dashboard
        fields = ["name", "slug", "is_public"]
