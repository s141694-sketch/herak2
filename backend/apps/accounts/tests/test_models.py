import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.accounts.models import Membership, Organization, Role, User

pytestmark = pytest.mark.django_db


def test_user_is_identified_by_normalized_email():
    user = User.objects.create_user(email="  Mazin@Example.COM ", password="correct-horse-battery", full_name="مازن")
    assert user.email == "mazin@example.com"
    assert user.check_password("correct-horse-battery")
    assert user.is_active and not user.is_staff and not user.is_superuser
    assert User.USERNAME_FIELD == "email"


def test_duplicate_email_is_rejected_regardless_of_case():
    User.objects.create_user(email="a@example.com", password="x" * 12)
    with pytest.raises(IntegrityError):
        User.objects.create_user(email="A@EXAMPLE.com", password="y" * 12)


def test_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x" * 12)


def test_organization_defaults_follow_the_spec():
    org = Organization.objects.create(name="مركز التدريب", slug="training-center")
    assert org.work_days == [6, 0, 1, 2, 3]  # Sunday to Thursday (Python weekday numbers)
    assert org.pre_submit_critical_behavior == Organization.PreSubmitBehavior.ALLOW_WITH_REASON
    assert org.ai_enabled is True
    assert org.ai_monthly_quota is None
    assert org.sso_session_hours == 8
    assert org.reminder_before_due_work_days == 1
    assert org.escalation_delay_work_days == 2
    assert org.brand_colors == {}


def test_organization_slug_is_unique():
    Organization.objects.create(name="A", slug="same")
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="B", slug="same")


def test_membership_roles_and_uniqueness():
    user = User.objects.create_user(email="u@example.com", password="x" * 12)
    org = Organization.objects.create(name="A", slug="a")
    assert set(Role.values) == {"admin", "author", "reviewer", "approver", "pending"}

    membership = Membership.objects.create(user=user, organization=org, role=Role.AUTHOR)
    assert membership.role == "author"
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, organization=org, role=Role.REVIEWER)


def test_membership_rejects_unknown_role():
    user = User.objects.create_user(email="u@example.com", password="x" * 12)
    org = Organization.objects.create(name="A", slug="a")
    with pytest.raises(ValidationError):
        Membership(user=user, organization=org, role="owner").full_clean()


def test_user_can_belong_to_several_organizations():
    user = User.objects.create_user(email="u@example.com", password="x" * 12)
    a = Organization.objects.create(name="A", slug="a")
    b = Organization.objects.create(name="B", slug="b")
    Membership.objects.create(user=user, organization=a, role=Role.ADMIN)
    Membership.objects.create(user=user, organization=b, role=Role.PENDING)
    assert list(user.memberships.order_by("organization__slug").values_list("organization__slug", "role")) == [
        ("a", "admin"),
        ("b", "pending"),
    ]
