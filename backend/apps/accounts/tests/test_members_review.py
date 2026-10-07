"""Members and passwords, from the independent review of phase 8 (D87, D89): the work a request does and its answer
are the same whether an email has an account; emails leave through the worker and are tried again; the guards on
role changes hold when two changes run at once; a review in progress counts as a stage that names a person; a
paused password sign-in waits the whole pause."""

import re
import threading
import time
from smtplib import SMTPException

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import members
from apps.accounts.models import Membership, Organization, Role, User
from apps.accounts.views import login_failures_key, login_pause_key
from apps.programs.tests.factories import member, program
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

PASSWORD = "a-long-enough-password-1"
LINK = re.compile(r"/set-password\?uid=([\w-]+)&token=([\w-]+)")


@pytest.fixture(autouse=True)
def committed(monkeypatch):
    monkeypatch.setattr("apps.accounts.members.transaction.on_commit", lambda callback, **kwargs: callback())


@pytest.fixture
def org(db):
    cache.clear()
    organization = Organization.objects.create(name="مركز أ", slug="a")
    with organization_context(organization):
        admin = member("admin@a.test", Role.ADMIN)
        author = member("author@a.test", Role.AUTHOR)
    for user in (admin, author):
        user.set_password(PASSWORD)
        user.save()
    yield organization
    cache.clear()


def forgot(email):
    return APIClient().post("/api/auth/password/forgot/", {"email": email}, format="json")


# --- Forgotten passwords (F5, F11) -------------------------------------------------------------------------------


def test_the_request_does_the_same_work_whether_the_email_has_an_account(org, monkeypatch):
    queued = []
    monkeypatch.setattr(members.send_reset_email, "apply_async", lambda args, **kwargs: queued.append(args))
    known, unknown = forgot("Author@a.test"), forgot("nobody@a.test")
    assert (known.status_code, unknown.status_code) == (202, 202) and known.json() == unknown.json()
    # Both only queue the email: no lookup decides anything in the request, and nothing is sent in it.
    assert queued == [("author@a.test",), ("nobody@a.test",)] and not mail.outbox


def test_a_failing_mail_server_changes_nothing_in_the_answer(org, monkeypatch):
    def broken(*args, **kwargs):
        raise SMTPException("the server is down")

    monkeypatch.setattr("apps.accounts.members.send_mail", broken)
    known, unknown = forgot("author@a.test"), forgot("nobody@a.test")
    assert (known.status_code, unknown.status_code) == (202, 202) and known.json() == unknown.json()


def test_one_address_gets_one_reset_email_in_a_while(org):
    answers = [forgot("author@a.test") for _ in range(3)]
    assert {a.status_code for a in answers} == {202}
    assert len(mail.outbox) == 1


# --- Invitations (F9, F21) ---------------------------------------------------------------------------------------


def test_an_invitation_that_fails_to_send_is_tried_again_and_the_member_stays(org, monkeypatch):
    attempts = []
    real_send = members.send_mail

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise SMTPException("try later")
        return real_send(*args, **kwargs)

    monkeypatch.setattr("apps.accounts.members.send_mail", flaky)
    client = APIClient()
    client.post("/api/auth/login/", {"email": "admin@a.test", "password": PASSWORD}, format="json")
    answer = client.post(
        "/api/organizations/current/members/", {"email": "new@a.test", "role": "author"}, format="json"
    )
    assert answer.status_code == 201
    assert len(attempts) == 2
    [invitation] = mail.outbox
    assert LINK.search(invitation.body)


def test_an_account_that_never_had_a_password_gets_a_link(org):
    elsewhere = Organization.objects.create(name="مركز ب", slug="b")
    with organization_context(elsewhere):
        sso_only = User.objects.create_user(email="sso@b.test", password=None)
        Membership.objects.create(user=sso_only, role=Role.AUTHOR)
    with organization_context(org):
        members.add_member(org, email="sso@b.test", role=Role.AUTHOR, actor=None)
    [invitation] = mail.outbox
    assert LINK.search(invitation.body)


# --- Guards that hold when two changes run at once (F6, F17) -----------------------------------------------------


def run_together(first, second, monkeypatch):
    """Runs two changes in two connections at once: the first pauses after its checks, the second starts then."""
    real_record = members.record
    paused = threading.Event()

    def slow_record(*args, **kwargs):
        if threading.current_thread().name == "first":
            paused.set()
            time.sleep(1.0)
        return real_record(*args, **kwargs)

    monkeypatch.setattr(members, "record", slow_record)
    errors = {}

    def runner(name, work):
        try:
            work()
        except Exception as exc:  # noqa: BLE001 - the test reads which of the two was refused
            errors[name] = exc
        finally:
            connection.close()

    threads = [
        threading.Thread(target=runner, args=("first", first), name="first"),
        threading.Thread(target=runner, args=("second", second), name="second"),
    ]
    threads[0].start()
    paused.wait(5)
    threads[1].start()
    for thread in threads:
        thread.join(10)
    return errors


@pytest.mark.django_db(transaction=True)
def test_two_admins_demoted_at_once_leave_the_organization_an_admin(monkeypatch):
    org = Organization.objects.create(name="مركز", slug="race")
    with organization_context(org):
        one, two = member("one@a.test", Role.ADMIN), member("two@a.test", Role.ADMIN)

    def demote(user):
        def work():
            with organization_context(org):
                members.set_role(Membership.objects.get(user=user), role=Role.AUTHOR, actor=None)

        return work

    errors = run_together(demote(one), demote(two), monkeypatch)
    with organization_context(org):
        assert Membership.objects.filter(role=Role.ADMIN).count() == 1
    assert getattr(errors.get("second"), "detail", {}).code == "last_admin"


@pytest.mark.django_db(transaction=True)
def test_an_admin_named_the_emergency_account_while_being_demoted_stays_an_admin(monkeypatch):
    from apps.sso import services as sso

    org = Organization.objects.create(name="مركز", slug="race2")
    with organization_context(org):
        keeper, other = member("keeper@a.test", Role.ADMIN), member("other@a.test", Role.ADMIN)
        config = IdentityProviderConfig.objects.create(
            issuer="https://idp.example.com",
            client_id="harak",
            client_secret_encrypted="",
            config_changed_at=timezone.now(),
            discovery_ok_at=timezone.now(),
        )

    def demote():
        with organization_context(org):
            members.set_role(Membership.objects.get(user=keeper), role=Role.AUTHOR, actor=None)

    def name_emergency():
        with organization_context(org):
            sso.set_policy(config, actor=other, enabled=True, emergency_user=keeper)

    run_together(demote, name_emergency, monkeypatch)
    with organization_context(org):
        config.refresh_from_db()
        role = Membership.objects.get(user=keeper).role
    # Either the demotion or the naming won; never an emergency account that is not an admin.
    assert config.emergency_user_id != keeper.pk or role == Role.ADMIN


# --- A review in progress names its people (F10) -----------------------------------------------------------------


def test_a_person_with_an_open_task_in_a_running_review_keeps_a_role_that_decides(org):
    from apps.programs import services as programs
    from apps.workflows import services as workflows
    from apps.workflows.models import StageTask
    from apps.workflows.tests.factories import two_stage_template

    with organization_context(org):
        admin = User.objects.get(email="admin@a.test")
        author = User.objects.get(email="author@a.test")
        reviewer = member("reviewer@a.test", Role.REVIEWER)
        approver = member("approver@a.test", Role.APPROVER)
        template = two_stage_template(admin, approver=approver)
        version = program(author, targets=[]).versions.get()
        programs.add_node(version, title="الوحدة", actor=author)
        workflows.submit(version, actor=author, role=Role.AUTHOR)
        task = StageTask.objects.get(closed_at__isnull=True)
        workflows.claim(task, actor=reviewer, role=Role.REVIEWER)
        # The template no longer names the approver; the running review's copy of the stages still does.
        workflows.save_template(
            template,
            actor=admin,
            name=template.name,
            is_default=True,
            stages=[{"name": "مراجعة", "assignee_role": "reviewer", "due_work_days": 2}],
        )
        for person in (reviewer, approver):  # the one who claimed the open task, and the one a stage names
            with pytest.raises(members.MemberError) as refused:
                members.set_role(Membership.objects.get(user=person), role=Role.PENDING, actor=admin)
            assert refused.value.detail.code == "member_assigned_to_stage"


# --- The pause after too many wrong passwords (F20) --------------------------------------------------------------


def test_a_paused_sign_in_waits_the_whole_pause_from_the_failure_that_reached_the_limit(org, settings):
    settings.LOGIN_ACCOUNT_FAILURES = 3
    client = APIClient()
    wrong = {"email": "author@a.test", "password": "not-the-password"}
    for _ in range(2):
        client.post("/api/auth/login/", wrong, format="json")
    # The window that counts failures nearly over, as when the first failure was almost a pause ago.
    redis, key = cache._cache.get_client(write=True), cache.make_and_validate_key(login_failures_key("author@a.test"))
    redis.expire(key, 5)
    client.post("/api/auth/login/", wrong, format="json")
    pause = cache.make_and_validate_key(login_pause_key("author@a.test"))
    assert redis.ttl(pause) > settings.LOGIN_ACCOUNT_PAUSE_MINUTES * 60 - 10
    refused = client.post("/api/auth/login/", {"email": "author@a.test", "password": PASSWORD}, format="json")
    assert refused.json()["error"]["code"] == "login_paused"
