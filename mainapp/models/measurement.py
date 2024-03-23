from django.db import models


class Measurement(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField()
    value = models.FloatField()

    metric = models.ForeignKey("Metric", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.date} = {self.value}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("metric", "date"), name="unique_measurement"
            )
        ]
