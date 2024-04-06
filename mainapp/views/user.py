from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views.generic import DeleteView, UpdateView

from mainapp.models.user import User


class UserUpdateView(SuccessMessageMixin, LoginRequiredMixin, UpdateView):
    object = User
    fields = ["username"]
    success_message = "Your profile was successfully updated."

    def get_object(self, queryset=None) -> User:
        assert isinstance(self.request.user, User)
        return self.request.user

    def get_success_url(self) -> str:
        return reverse("profile")


class UserDeleteView(LoginRequiredMixin, DeleteView):
    object = User
    success_url = "/"

    def get_object(self, queryset=None) -> User:
        assert isinstance(self.request.user, User)
        return self.request.user
