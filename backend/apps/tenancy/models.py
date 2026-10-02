"""Organization scoping enforced in one place for every tenant table.

Every tenant model inherits OrganizationScopedModel. Its default manager only
ever returns rows of the active organization and refuses to run without one;
saving assigns the active organization and rejects rows, or related rows, that
belong to another organization. The only way across organizations is the
explicit `all_organizations` manager, which is meant for system jobs and must
never be used in request handling.
"""

from django.db import models

from .context import current_organization_id


class CrossOrganizationError(ValueError):
    """Raised when a row or one of its relations belongs to a different organization."""


class OrganizationScopedQuerySet(models.QuerySet):
    pass


class OrganizationScopedManager(models.Manager.from_queryset(OrganizationScopedQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(organization_id=current_organization_id())


class OrganizationScopedModel(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="%(app_label)s_%(class)s",
    )

    objects = OrganizationScopedManager()
    all_organizations = models.Manager()  # noqa: DJ012 - fields, then managers, as the style guide says

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        active = current_organization_id()
        if self.organization_id is None:
            self.organization_id = active
        elif self.organization_id != active:
            raise CrossOrganizationError(
                f"{type(self).__name__} belongs to organization {self.organization_id}, active is {active}"
            )
        self._check_related_organizations(active)
        super().save(*args, **kwargs)

    def _check_related_organizations(self, active: int) -> None:
        for field in self._meta.concrete_fields:
            if not field.is_relation or field.name == "organization":
                continue
            if not issubclass(field.related_model, OrganizationScopedModel):
                continue
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            related_org = (
                field.related_model.all_organizations.filter(pk=related_id)
                .values_list("organization_id", flat=True)
                .first()
            )
            if related_org != active:
                raise CrossOrganizationError(f"{type(self).__name__}.{field.name} points outside organization {active}")
