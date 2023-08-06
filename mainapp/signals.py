from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.signals import pre_social_login
from django.dispatch import receiver

from .models import User


@receiver(pre_social_login)
def link_to_local_user(sender, request, sociallogin: SocialLogin, **kwargs):
    if sociallogin.is_existing:
        return
    email_address = sociallogin.email_addresses[0]
    if not email_address.verified:
        # The user provided by the platform needs to be considered as
        # verified to be able to be linked to the existing account.
        # Note: it is not enough that the *account* is verified (it should be the *email*)
        return
    try:
        user = User.get_by_email(email_address.email)
        sociallogin.connect(request, user)
    except User.DoesNotExist:
        pass
