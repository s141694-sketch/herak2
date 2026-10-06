"""Members of an organization (spec 2.1: the training manager runs the space and its users; D87).

An admin adds people by email with a role, and changes roles. Someone new gets an invitation whose link sets their
password; someone with an account already is told they were added; where the organization signs people in
through its provider (enforced), the invitation says to sign in there. Anyone who forgot their password asks for a
new link, and the answer never says whether the email has an account.

What a role change must not break: the organization keeps an admin, its emergency account stays an admin (D66),
and a person a workflow stage names keeps a role that decides (D61).
"""

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.audit.services import record
from apps.core.errors import Conflict

from .models import Membership, Role, User

EDITABLE_ROLES = [role for role, _ in Role.choices]


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


def _invite(user: User, organization, *, new: bool) -> None:
    name = organization.name
    if _signs_in_through_provider(organization):
        _send(
            user,
            (f"أُضفت إلى {name} في حراك", f"You were added to {name} on Harak"),
            f"أضافك مدير التدريب إلى {name} في حراك. ادخل عبر مزوّد مؤسستك: {settings.APP_URL}",
            f"Your training manager added you to {name} on Harak. Sign in through your organization: "
            f"{settings.APP_URL}",
        )
    elif new:
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
            (f"أُضفت إلى {name} في حراك", f"You were added to {name} on Harak"),
            f"أضافك مدير التدريب إلى {name} في حراك. ادخل بحسابك المعتاد: {settings.APP_URL}",
            f"Your training manager added you to {name} on Harak. Sign in with your usual account: {settings.APP_URL}",
        )


@transaction.atomic
def add_member(organization, *, email: str, role: str, full_name: str = "", actor) -> Membership:
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    new = user is None
    if new:
        user = User.objects.create_user(email=email, password=None, full_name=full_name.strip())
    if Membership.objects.filter(user=user).exists():
        raise MemberError("this person is already a member", code="member_exists")
    try:
        with transaction.atomic():
            membership = Membership.objects.create(user=user, role=role)
    except IntegrityError as exc:  # added twice at once
        raise MemberError("this person is already a member", code="member_exists") from exc
    record("membership.added", actor=actor, target=membership, payload={"user": user.pk, "role": role, "new": new})
    transaction.on_commit(lambda: _invite(user, organization, new=new and not user.has_usable_password()))
    return membership


@transaction.atomic
def set_role(membership: Membership, *, role: str, actor) -> Membership:
    from apps.sso.models import IdentityProviderConfig
    from apps.workflows.models import STAGE_ROLES, Stage

    membership = Membership.objects.select_for_update().get(pk=membership.pk)
    before = membership.role
    if role == before:
        return membership
    if before == Role.ADMIN and role != Role.ADMIN:
        admins = Membership.objects.select_for_update().filter(role=Role.ADMIN)
        if admins.count() <= 1:
            raise MemberError("the organization needs an admin", code="last_admin")
        if IdentityProviderConfig.objects.filter(emergency_user=membership.user).exists():
            raise MemberError("the emergency account stays an admin", code="member_is_emergency")
    if role not in STAGE_ROLES and Stage.objects.filter(assignee_user=membership.user).exists():
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


def forgot_password(email: str) -> None:
    """A link to choose a new password, to an active account with this email; nothing otherwise. The caller answers
    the same either way."""
    user = User.objects.filter(email=email.strip().lower(), is_active=True).first()
    if user is None:
        return
    link = _link(user)
    _send(
        user,
        ("كلمة مرور جديدة في حراك", "A new password on Harak"),
        f"طُلب تغيير كلمة مرور حسابك في حراك. اختر كلمة جديدة من هذا الرابط، وهو صالح ثلاثة أيام:\n{link}\n"
        "إن لم تطلب ذلك فتجاهل هذه الرسالة.",
        f"A new password was asked for your Harak account. Choose one from this link, valid for three days:\n{link}\n"
        "If you did not ask for it, ignore this message.",
    )


def set_password(uid: str, token: str, password: str) -> User:
    """Sets the password a link's person chose. The link works once: the new password changes what its token signs."""
    try:
        user = User.objects.get(pk=int(force_str(urlsafe_base64_decode(uid))))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist) as exc:
        raise PasswordLinkInvalid() from exc
    if not user.is_active or not default_token_generator.check_token(user, token):
        raise PasswordLinkInvalid()
    validate_password(password, user)  # raises ValidationError
    user.set_password(password)
    user.save(update_fields=["password"])
    return user


__all__ = ["EDITABLE_ROLES", "MemberError", "PasswordLinkInvalid", "ValidationError", "add_member", "set_role"]
