import base64
import binascii

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.services import record
from apps.core.errors import Conflict
from apps.programs import services as program_services
from apps.programs.models import Block, Node

from .models import Comment, CommentReply


class CommentError(Conflict):
    default_code = "comment_error"


REOPENING_ROLES = {Role.REVIEWER, Role.APPROVER, Role.ADMIN}


def valid_anchor(anchor) -> bool:
    if anchor is None:
        return True
    if not isinstance(anchor, dict) or set(anchor) != {"start", "end"}:
        return False
    try:
        return all(len(base64.b64decode(anchor[k], validate=True)) <= 1024 for k in ("start", "end"))
    except (binascii.Error, ValueError, TypeError):
        return False


@transaction.atomic
def create_comment(*, program, version, author, body, category, block_key=None, node_key=None, anchor=None, quoted=""):
    if block_key is None and node_key is None:
        raise CommentError("say which block or node the comment is about", code="comment_target_missing")
    if not version.is_editable:
        # Rows are authoritative for a locked version. A draft's live document may hold blocks that
        # have not reached their first save yet, so its keys are accepted as given.
        exists = (
            Block.objects.filter(version=version, block_key=block_key).exists()
            if block_key
            else Node.objects.filter(version=version, node_key=node_key).exists()
        )
        if not exists:
            raise CommentError("that block or node is not in this version", code="comment_target_unknown")
    comment = Comment.objects.create(
        program=program,
        version=version,
        block_key=block_key,
        node_key=node_key,
        anchor=anchor,
        quoted=quoted,
        body=body,
        category=category,
        author=author,
    )
    record("comment.created", actor=author, target=comment, payload={"category": category, "version": version.number})
    return comment


def add_reply(comment: Comment, *, author, body) -> CommentReply:
    reply = CommentReply.objects.create(comment=comment, author=author, body=body)
    record("comment.replied", actor=author, target=comment)
    return reply


@transaction.atomic
def resolve(comment: Comment, *, actor, role) -> Comment:
    if not program_services.can_edit(comment.program, actor, role):
        raise CommentError("only the program's editors mark comments resolved", code="comment_not_allowed")
    comment = Comment.objects.select_for_update().select_related("program").get(pk=comment.pk)
    if comment.status == Comment.Status.RESOLVED:
        raise CommentError("this comment is already resolved", code="comment_already_resolved")
    comment.status = Comment.Status.RESOLVED
    comment.resolved_by = actor
    comment.resolved_at = timezone.now()
    comment.save()
    record("comment.resolved", actor=actor, target=comment)
    return comment


@transaction.atomic
def reopen(comment: Comment, *, actor, role) -> Comment:
    if role not in REOPENING_ROLES and comment.author_id != actor.pk:
        raise CommentError("reviewers reopen comments", code="comment_not_allowed")
    comment = Comment.objects.select_for_update().select_related("program").get(pk=comment.pk)
    if comment.status == Comment.Status.OPEN:
        raise CommentError("this comment is already open", code="comment_not_resolved")
    comment.status = Comment.Status.OPEN
    comment.resolved_by = None
    comment.resolved_at = None
    comment.save()
    record("comment.reopened", actor=actor, target=comment)
    return comment
