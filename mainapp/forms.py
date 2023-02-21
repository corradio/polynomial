from django import forms

from mainapp.models import Metric, Organization, OrganizationUser


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
    email = forms.EmailField(max_length=75)

    def save(self, *args, **kwargs):
        """Sends an invite to the user"""
        # try:
        #     user = get_user_model().objects.get(
        #         email__iexact=self.cleaned_data["email"]
        #     )
        # except get_user_model().DoesNotExist:
        #     user = invitation_backend().invite_by_email(
        #         self.cleaned_data["email"],
        #         **{
        #             "domain": get_current_site(self.request),
        #             "organization": self.organization,
        #             "sender": self.request.user,
        #         }
        #     )
        # # Send a notification email to this user to inform them that they
        # # have been added to a new organization.
        # invitation_backend().send_notification(
        #     user,
        #     **{
        #         "domain": get_current_site(self.request),
        #         "organization": self.organization,
        #         "sender": self.request.user,
        #     }
        # )
        # return OrganizationUser.objects.create(
        #     user=user,
        #     organization=self.organization,
        #     is_admin=self.cleaned_data["is_admin"],
        # )

    class Meta:
        model = OrganizationUser
        exclude = ("user", "organization")
