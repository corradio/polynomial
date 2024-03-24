from typing import Union

from django.contrib.auth.models import AnonymousUser
from django.db import models

from mainapp.models.user import User


class Marker(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    text = models.CharField(max_length=128)

    metric = models.ForeignKey("Metric", on_delete=models.CASCADE)

    def can_edit(self, user: Union[User, AnonymousUser]) -> bool:
        return self.metric.can_edit(user)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("metric", "date"), name="unique_marker")
        ]
