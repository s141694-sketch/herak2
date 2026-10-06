from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.tenancy.models import OrganizationScopedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra):
        if not email or not email.strip():
            raise ValueError("an email address is required")
        user = self.model(email=self.normalize_email(email.strip()).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """A person. Global, not organization-scoped: one user can belong to several organizations."""

    email = models.EmailField(_("email"), max_length=254, unique=True)
    full_name = models.CharField(_("full name"), max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        # unique=True satisfies Django's USERNAME_FIELD check; the functional constraint makes it case-insensitive.
        constraints = [models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique")]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


def default_work_days() -> list[int]:
    """Sunday to Thursday, as Python weekday numbers (Monday=0)."""
    return [6, 0, 1, 2, 3]


def validate_work_days(value) -> None:
    """At least one work day, each a weekday number 0 (Monday) to 6: due times are counted in them (spec 6.3)."""
    valid = isinstance(value, list) and value and all(type(d) is int and 0 <= d <= 6 for d in value)
    if not valid:
        raise ValidationError("work days are a non-empty list of weekday numbers 0 (Monday) to 6")


class Organization(models.Model):
    """A tenant. Every tenant-scoped table points here through organization_id."""

    class PreSubmitBehavior(models.TextChoices):
        BLOCK = "block", _("block submission on critical findings")
        ALLOW_WITH_REASON = "allow_with_reason", _("allow submission with a written reason")

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    # The organization's identity (spec 4.1), which its exported files carry: a logo in the file store, and colors.
    logo_file = models.ForeignKey("files.File", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    brand_colors = models.JSONField(default=dict, blank=True)
    work_days = models.JSONField(default=default_work_days, validators=[validate_work_days])
    pre_submit_critical_behavior = models.CharField(
        max_length=20, choices=PreSubmitBehavior.choices, default=PreSubmitBehavior.ALLOW_WITH_REASON
    )
    ai_enabled = models.BooleanField(default=True)
    # Monthly AI quota; null means no quota configured yet (open issue 13 in the spec).
    ai_monthly_quota = models.PositiveIntegerField(null=True, blank=True)
    sso_session_hours = models.PositiveSmallIntegerField(default=8)
    # Admins and approvers must use a second factor with a password (spec 7.1).
    mfa_required_for_managers = models.BooleanField(default=False)
    reminder_before_due_work_days = models.PositiveSmallIntegerField(default=1)
    escalation_delay_work_days = models.PositiveSmallIntegerField(default=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", _("training manager")
    AUTHOR = "author", _("author")
    REVIEWER = "reviewer", _("reviewer")
    APPROVER = "approver", _("approver")
    PENDING = "pending", _("pending assignment")


class Membership(OrganizationScopedModel):
    """Links a user to an organization with one role. Pending members have no permissions.

    Organization-scoped like every tenant table; the login and switch flows,
    which run before a context exists, go through `Membership.all_organizations`.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organization"], name="accounts_membership_unique")]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"


class TOTPDevice(models.Model):
    """A person's second factor (spec 7.1, D67): a TOTP secret, stored encrypted. It belongs to the person, not to
    one organization: the same code serves every organization they work in (a global table, D70)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_device")
    secret_encrypted = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # The last time step a code was accepted for: a code is never accepted twice.
    last_step = models.BigIntegerField(default=0)
    # Wrong codes in a row, from any session; enough of them lock the factor until ``locked_until``.
    failures = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"TOTP of {self.user}"
