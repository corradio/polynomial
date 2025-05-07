from allauth.account.forms import SignupForm
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV3


class ReCaptchaSignupForm(SignupForm):
    captcha = ReCaptchaField(widget=ReCaptchaV3(required_score=0.85))

    def save(self, request):
        user = super().save(request)
        return user
