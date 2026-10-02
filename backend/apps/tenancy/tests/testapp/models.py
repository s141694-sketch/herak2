from django.db import models

from apps.tenancy.models import OrganizationScopedModel


class Widget(OrganizationScopedModel):
    name = models.CharField(max_length=50)


class Part(OrganizationScopedModel):
    widget = models.ForeignKey(Widget, on_delete=models.CASCADE, related_name="parts")
    name = models.CharField(max_length=50)
