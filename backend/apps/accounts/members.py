"""Members of an organization (spec 2.1: the training manager runs the space and its users; D87).

An admin adds people by email with a role, and changes roles. Joining takes the person's acceptance (D90): what
the admin makes is an invitation, which grants and shows nothing until its person accepts it. Someone without a
password gets a link to choose one, which proves the email and accepts; someone with an account signs in and
accepts or declines; where the organization signs people in through its provider (enforced), the invitation says
to sign in there, and that sign-in accepts. An admin cancels an invitation not yet answered. Anyone who forgot
their password asks for a new link, and the answer never says whether the email has an account.

What a role change must not break: the organization keeps an admin, its emergency account stays an admin (D66),
and a person a workflow stage or a review in progress names keeps a role that decides (D61). Role changes, and the
naming of the emergency account, take the organization's row lock, so two at once cannot both pass these checks.

Emails leave through the worker and are tried again when the mail server fails (spec 7.7). A forgotten password
only queues its email, for any address, so neither the answer nor the work in the request depends on whether the
address has an account; one address gets one such email in PASSWORD_RESET_EMAIL_MINUTES (phase 8 review, D89).
"""

import hashlib

import sentry_sdk
import structlog
from celery import shared_task
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.audit.services import record
from apps.core.errors import Conflict

from .models import Membership, Organization, Role, User

log = structlog.get_logger("harak2.accounts")
EDITABLE_ROLES = [role for role, _ in Role.choices]
# An email the mail server refused is tried again this many times, after 1, 2, 4, 8 and 16 minutes.
EMAIL_RETRIES = 5


class MemberError(Conflict):
    default_code = "member_error"


class PasswordLinkInvalid(Exception):
    pass


def _link(user: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.APP_URL.rstrip('/')}/set-password?uid={uid}&token={token}"


def _signs_in_through_provider(organization) -> bool:
    from apps.sso.models import IdentityProviderConfig

    return IdentityProviderConfig.all_organizations.filter(organization=organization, enforced=True).exists()


def _send(user: User, subject: tuple[str, str], arabic: str, english: str) -> None:
    send_mail(f"{subject[0]} | {subject[1]}", f"{arabic}\n\n{english}", settings.DEFAULT_FROM_EMAIL, [user.email])


def _invite(user: User, organization) -> None:
    name = organization.name
    if _signs_in_through_provider(organization):
        _send(
            user,
            (f"دعوة إلى {name} في حراك", f"An invitation to {name} on Harak"),
            f"دعاك مدير التدريب إلى {name} في حراك. ادخل عبر مزوّد مؤسستك لتقبل الدعوة: {settings.APP_URL}",
            f"Your training manager invited you to {name} on Harak. Sign in through your organization to accept: "
            f"{settings.APP_URL}",
        )
    elif not user.has_usable_password():  # new, or an account that has only ever signed in through a provider
        link = _link(user)
        _send(
            user,
            (f"دعوة إلى {name} في حراك", f"An invitation to {name} on Harak"),
            f"دعاك مدير التدريب إلى {name} في حراك. اختر كلمة مرورك من هذا الرابط، وهو صالح ثلاثة أيام:\n{link}",
            f"Your training manager invited you to {name} on Harak. Choose your password from this link, valid for "
            f"three days:\n{link}",
        )
    else:
        _send(
            user,
            (f"دعوة إلى {name} في حراك", f"An invitation to {name} on Harak"),
            f"دعاك مدير التدريب إلى {name} في حراك. ادخل بحسابك المعتاد لتقبل الدعوة أو ترفضها: {settings.APP_URL}",
            f"Your training manager invited you to {name} on Harak. Sign in with your usual account to accept or "
            f"decline: {settings.APP_URL}",
        )


def _queue(task, *args) -> None:
    """The worker sends it; a broker that is down must not fail what was committed, so it is logged instead."""
    try:
        task.apply_async(args, retry=False)
    except Exception as exc:
        log.error("accounts.email_not_queued", task=task.name, error=str(exc))
        sentry_sdk.capture_exception(exc)


def _try_again(task, exc, **context) -> None:
    if task.request.retries >= EMAIL_RETRIES:
        log.error("accounts.email_failed", task=task.name, error=str(exc), **context)
        return
    log.warning("accounts.email_retry", task=task.name, error=str(exc), attempt=task.request.retries + 1, **context)
    raise task.retry(exc=exc, countdown=60 * 2**task.request.retries)


@shared_task(name="accounts.send_invitation", bind=True, max_retries=EMAIL_RETRIES, ignore_result=True)
def send_invitation(self, user_id: int, organization_id: int) -> None:
    user, organization = User.objects.get(pk=user_id), Organization.objects.get(pk=organization_id)
    try:
        _invite(user, organization)
    except Exception as exc:
        _try_again(self, exc, user=user_id, organization=organization_id)


@shared_task(name="accounts.send_reset_email", bind=True, max_retries=EMAIL_RETRIES, ignore_result=True)
def send_reset_email(self, email: str) -> None:
    """A link to choose a new password, to an active account with this email; nothing otherwise."""
    user = User.objects.filter(email=email, is_active=True).first()
    if user is None:
        return
    link = _link(user)
    try:
        _send(
            user,
            ("كلمة مرور جديدة في حراك", "A new password on Harak"),
            f"طُلب تغيير كلمة مرور حسابك في حراك. اختر كلمة جديدة من هذا الرابط، وهو صالح ثلاثة أيام:\n{link}\n"
            "إن لم تطلب ذلك فتجاهل هذه الرسالة.",
            f"A new password was asked for your Harak account. Choose one from this link, valid for three days:\n"
            f"{link}\nIf you did not ask for it, ignore this message.",
        )
    except Exception as exc:
        _try_again(self, exc, user=user.pk)


def _lock_organization() -> None:
    """Role changes and the naming of the emergency account wait for each other in one organization (F6, F17)."""
    from apps.tenancy.context import current_organization_id

    Organization.objects.select_for_update().get(pk=current_organization_id())


@transaction.atomic
def add_member(organization, *, email: str, role: str, full_name: str = "", actor) -> Membership:
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    new = user is None
    if new:
        user = User.objects.create_user(email=email, password=None, full_name=full_name.strip())
    if Membership.with_invitations.filter(user=user).exists():
        raise MemberError("this person is already a member", code="member_exists")
    try:
        with transaction.atomic():
            # An invitation until the person accepts it (D90), whoever they are.
            membership = Membership.with_invitations.create(user=user, role=role, accepted_at=None)
    except IntegrityError as exc:  # added twice at once
        raise MemberError("this person is already a member", code="member_exists") from exc
    record("membership.added", actor=actor, target=membership, payload={"user": user.pk, "role": role, "new": new})
    transaction.on_commit(lambda: _queue(send_invitation, user.pk, organization.pk))
    return membership


@transaction.atomic
def set_role(membership: Membership, *, role: str, actor) -> Membership:
    from apps.sso.models import IdentityProviderConfig
    from apps.workflows.models import STAGE_ROLES

    _lock_organization()
    membership = Membership.with_invitations.select_for_update().get(pk=membership.pk)
    before = membership.role
    if role == before:
        return membership
    # An invitation counts as no one's admin and no emergency account yet: only accepted memberships are guarded.
    if before == Role.ADMIN and role != Role.ADMIN and not membership.is_invitation:
        if Membership.objects.filter(role=Role.ADMIN).count() <= 1:
            raise MemberError("the organization needs an admin", code="last_admin")
        if IdentityProviderConfig.objects.filter(emergency_user=membership.user).exists():
            raise MemberError("the emergency account stays an admin", code="member_is_emergency")
    if role not in STAGE_ROLES and _named_by_a_stage(membership.user):
        raise MemberError("a workflow stage names this person", code="member_assigned_to_stage")
    membership.role = role
    membership.save(update_fields=["role"])
    record(
        "membership.role_changed",
        actor=actor,
        target=membership,
        payload={"from": before, "to": role, "user": membership.user_id},
    )
    return membership


@transaction.atomic
def cancel_invitation(membership: Membership, *, actor) -> None:
    """An admin withdraws an invitation not yet answered. A member is never removed (D87)."""
    membership = Membership.with_invitations.select_for_update().get(pk=membership.pk)
    if not membership.is_invitation:
        raise MemberError("only an invitation not yet accepted is cancelled", code="member_not_invited")
    record("membership.invitation_cancelled", actor=actor, target=membership, payload={"user": membership.user_id})
    membership.delete()


def _invitation_of(user: User, pk: int) -> Membership:
    """The person's own invitation, not yet answered; any other id is not found (Membership.DoesNotExist)."""
    return Membership.including_invitations.select_for_update().get(pk=pk, user=user, accepted_at__isnull=True)


def _accept(membership: Membership, *, how: str) -> None:
    from apps.tenancy.context import organization_context

    membership.accepted_at = timezone.now()
    with organization_context(membership.organization_id):
        Membership.with_invitations.filter(pk=membership.pk).update(accepted_at=membership.accepted_at)
        record(
            "membership.accepted",
            actor=membership.user,
            target=membership,
            payload={"user": membership.user_id, "role": membership.role, "how": how},
        )


@transaction.atomic
def accept_invitation(user: User, pk: int) -> Membership:
    membership = _invitation_of(user, pk)
    _accept(membership, how="answered")
    return membership


@transaction.atomic
def decline_invitation(user: User, pk: int) -> None:
    from apps.tenancy.context import organization_context

    membership = _invitation_of(user, pk)
    with organization_context(membership.organization_id):
        record("membership.declined", actor=user, target=membership, payload={"user": user.pk})
        Membership.with_invitations.filter(pk=membership.pk).delete()


def accept_by_signing_in(user: User) -> None:
    """Signing in through the provider of the organization in context accepts its invitation (D90); a first
    sign-in with none makes a pending member (D65)."""
    invitation = Membership.with_invitations.filter(user=user).first()
    if invitation is None:
        try:
            with transaction.atomic():
                Membership.objects.create(user=user, role=Role.PENDING)
        except IntegrityError:  # a first sign-in of the same person at the same moment made it
            pass
    elif invitation.is_invitation:
        _accept(invitation, how="provider")


def _named_by_a_stage(user: User) -> bool:
    """A template's stage names the person, or a review in progress does: its own copy of the stages, or its open
    task, assigned to them or claimed by them (F10)."""
    from django.db.models import Q

    from apps.workflows.models import Stage, StageTask, WorkflowInstance

    if Stage.objects.filter(assignee_user=user).exists():
        return True
    if StageTask.objects.filter(Q(assignee_user=user) | Q(claimed_by=user), closed_at__isnull=True).exists():
        return True
    running = WorkflowInstance.objects.filter(outcome=WorkflowInstance.Outcome.OPEN).values_list("stages", flat=True)
    return any(stage.get("assignee_user") == user.pk for stages in running for stage in stages)


def _reset_key(email: str) -> str:
    return "password-reset-email:" + hashlib.sha256(email.encode()).hexdigest()


def forgot_password(email: str) -> None:
    """Queues the email with a link to choose a new password, whatever the address: the worker sends it only to an
    active account. One address gets one in PASSWORD_RESET_EMAIL_MINUTES; the caller answers the same either way."""
    email = email.strip().lower()
    if not cache.add(_reset_key(email), 1, timeout=settings.PASSWORD_RESET_EMAIL_MINUTES * 60):
        return
    _queue(send_reset_email, email)


def set_password(uid: str, token: str, password: str) -> User:
    """Sets the password a link's person chose. The link works once: the new password changes what its token signs."""
    try:
        user = User.objects.get(pk=int(force_str(urlsafe_base64_decode(uid))))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist) as exc:
        raise PasswordLinkInvalid() from exc
    if not user.is_active or not default_token_generator.check_token(user, token):
        raise PasswordLinkInvalid()
    validate_password(password, user)  # raises ValidationError
    proves_the_invitation = not user.has_usable_password()
    with transaction.atomic():
        user.set_password(password)
        user.save(update_fields=["password"])
        if proves_the_invitation:
            # The link went to an account without a password, as an invitation's does: choosing one from it proves
            # the email, and accepts the person's invitations (D90). A reset of an account with a password does not.
            for invitation in Membership.including_invitations.select_for_update().filter(
                user=user, accepted_at__isnull=True
            ):
                _accept(invitation, how="password_link")
    return user


__all__ = [
    "EDITABLE_ROLES",
    "MemberError",
    "PasswordLinkInvalid",
    "ValidationError",
    "accept_by_signing_in",
    "accept_invitation",
    "add_member",
    "cancel_invitation",
    "decline_invitation",
    "set_role",
]
