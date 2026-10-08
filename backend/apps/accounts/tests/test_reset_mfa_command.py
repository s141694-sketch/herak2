"""The operator's way back for a person who lost their second factor and works in more than one organization
(D92): no one organization's admin may remove it (D70), so the operator does, and each organization's audit log
says so."""

import io

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import Organization, Role, TOTPDevice
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    a = Organization.objects.create(name="أ", slug="a")
    b = Organization.objects.create(name="ب", slug="b")
    with organization_context(a):
        person = member("person@example.com", Role.AUTHOR)
    with organization_context(b):
        from apps.accounts.models import Membership

        Membership.objects.create(user=person, role=Role.REVIEWER)
    TOTPDevice.objects.create(user=person, secret_encrypted="x", confirmed_at=timezone.now())
    return {"a": a, "b": b, "person": person}


def reset(email):
    out = io.StringIO()
    call_command("reset_mfa", "--email", email, "--reason", "called their manager", stdout=out)
    return out.getvalue()


def test_the_operator_removes_the_factor_and_every_organization_is_told(world):
    out = reset(" Person@Example.com ")
    assert not TOTPDevice.objects.filter(user=world["person"]).exists()
    logged = AuditLog.all_organizations.filter(event="mfa.reset")
    assert {entry.organization_id for entry in logged} == {world["a"].pk, world["b"].pk}
    assert all(
        entry.payload == {"user": world["person"].pk, "by": "operator", "reason": "called their manager"}
        for entry in logged
    )
    assert "person@example.com" in out


def test_an_emergency_account_keeps_its_factor(world):
    with organization_context(world["a"]):
        IdentityProviderConfig.objects.create(
            issuer="https://idp.a.test",
            client_id="harak",
            client_secret_encrypted="x",
            emergency_user=world["person"],
            config_changed_at=timezone.now(),
        )
    with pytest.raises(CommandError, match="emergency"):
        reset("person@example.com")
    assert TOTPDevice.objects.filter(user=world["person"]).exists()


@pytest.mark.parametrize("email", ["nobody@example.com", "not an email"])
def test_an_unknown_person_is_refused(world, email):
    with pytest.raises(CommandError):
        reset(email)


def test_a_person_without_a_factor_is_told_so(world):
    TOTPDevice.objects.all().delete()
    with pytest.raises(CommandError, match="no second factor"):
        reset("person@example.com")
