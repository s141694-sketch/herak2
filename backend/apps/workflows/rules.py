"""The conditions of spec 6.2 around a submission (tasks 5.4 and 5.5), checked under the version's lock."""

from apps.accounts.models import Organization
from apps.comments.models import Comment
from apps.programs.models import ProgramVersion
from apps.quality.models import Finding, Severity
from apps.quality.rules import program as program_rules
from apps.quality.snapshot import load_snapshot

from .models import StageDecision, StageTask, WorkflowInstance

MAX_REASON = 2000


class RuleRefused(Exception):
    """Raised as a WorkflowError by the services; kept apart so this module does not import them."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def critical_findings(version: ProgramVersion) -> list:
    """The rules' critical findings on the version's rows as they are now, less those dismissed in its report."""
    _, findings = program_rules.analyze(load_snapshot(version))
    dismissed = set(
        Finding.objects.filter(
            report__version=version, source=Finding.Source.RULE, dismissed_at__isnull=False
        ).values_list("fingerprint", flat=True)
    )
    return [f for f in findings if f.severity == Severity.CRITICAL and f.fingerprint not in dismissed]


def pre_submit(version: ProgramVersion, reason: str) -> dict:
    """Spec 6.2.1: critical findings block the submission, or let it through with a reason the reviewer sees,
    as the organization chose. Returns what the submission keeps."""
    critical = critical_findings(version)
    if not critical:
        return {}
    organization = Organization.objects.get(pk=version.organization_id)
    if organization.pre_submit_critical_behavior == Organization.PreSubmitBehavior.BLOCK:
        raise RuleRefused("fix or dismiss the critical findings before submitting", "critical_findings_block")
    reason = (reason or "").strip()
    if not reason:
        raise RuleRefused(
            "say why the version is submitted with critical findings", "critical_findings_reason_required"
        )
    return {
        "reason": reason[:MAX_REASON],
        "critical": [
            {
                "kind": f.kind,
                "node_key": f.node_key,
                "block_key": f.block_key,
                "competency_key": f.competency_key,
                "params": f.params,
            }
            for f in critical
        ],
    }


def open_comments(version: ProgramVersion):
    """The program's open comments this version shows: written on it or on an earlier version."""
    return Comment.objects.filter(
        program_id=version.program_id, status=Comment.Status.OPEN, version__number__lte=version.number
    )


def decision(version: ProgramVersion, instance: WorkflowInstance, task: StageTask, decided: str) -> None:
    """Spec 6.2.2 and 6.2.3: open must_fix comments block final approval; a return needs an open comment (D55)."""
    if decided == StageDecision.Decision.RETURN:
        if not Comment.objects.filter(version=version, status=Comment.Status.OPEN).exists():
            raise RuleRefused(
                "write at least one comment on this version before returning it", "return_comment_required"
            )
        return
    final = task.stage == len(instance.stages)
    if final and open_comments(version).filter(category=Comment.Category.MUST_FIX).exists():
        raise RuleRefused("comments that must be fixed are still open", "open_must_fix")


def resolved_must_fix(instance: WorkflowInstance):
    """Spec 6.2.7: on a resubmission, the must_fix comments marked resolved since the return, for the reviewer."""
    previous = instance.previous
    if previous is None or previous.closed_at is None:
        return Comment.objects.none()
    return Comment.objects.filter(
        program_id=instance.version.program_id,
        category=Comment.Category.MUST_FIX,
        status=Comment.Status.RESOLVED,
        resolved_at__gte=previous.closed_at,
    ).select_related("resolved_by", "author")
