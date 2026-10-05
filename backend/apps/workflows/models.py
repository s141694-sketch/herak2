"""Approval workflows (spec 4.5, 6.1-6.3; tasks 5.2 and 5.3).

A WorkflowTemplate is a sequence of stages, each with whoever is responsible (one person, or a role whose
holders claim the task), a time allowed in work days and what a resubmission after a return does. A program
follows its chosen template or the organization's default (D53).

Submitting a version starts a WorkflowInstance holding a copy of the stages as they were then, so editing a
template never changes a review in progress. Each entry into a stage is a StageTask with its due time; the
decision taken on it is a StageDecision. Status changes still go only through apps.programs.lifecycle.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.models import Role
from apps.programs.models import Program, ProgramVersion
from apps.tenancy.models import OrganizationScopedModel

# Who may be responsible for a stage by role: those whose role is to review or decide.
STAGE_ROLES = (Role.REVIEWER, Role.APPROVER, Role.ADMIN)


class Resubmit(models.TextChoices):
    SAME_STAGE = "same_stage", "same_stage"
    RESTART = "restart", "restart"


class WorkflowTemplate(OrganizationScopedModel):
    name = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"], condition=Q(is_default=True), name="workflows_one_default_template"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Stage(OrganizationScopedModel):
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    assignee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    assignee_role = models.CharField(max_length=20, blank=True)
    due_work_days = models.PositiveSmallIntegerField(default=3)
    resubmit = models.CharField(max_length=20, choices=Resubmit.choices, default=Resubmit.SAME_STAGE)

    class Meta:
        ordering = ["template", "order"]
        constraints = [
            models.UniqueConstraint(fields=["template", "order"], name="workflows_stage_order_unique"),
            models.CheckConstraint(
                condition=(Q(assignee_user__isnull=False) & Q(assignee_role=""))
                | (Q(assignee_user__isnull=True) & Q(assignee_role__in=STAGE_ROLES)),
                name="workflows_stage_one_assignee",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template} #{self.order} {self.name}"


class ProgramWorkflow(OrganizationScopedModel):
    """The template a program follows, when it is not the organization's default."""

    program = models.OneToOneField(Program, on_delete=models.CASCADE, related_name="workflow_choice")
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.PROTECT, related_name="programs")

    def __str__(self) -> str:
        return f"{self.program} -> {self.template}"


class WorkflowInstance(OrganizationScopedModel):
    """One submission of a version and its way through the stages."""

    class Outcome(models.TextChoices):
        OPEN = "", "open"
        APPROVED = "approved", "approved"
        RETURNED = "returned", "returned"
        WITHDRAWN = "withdrawn", "withdrawn"
        CANCELLED = "cancelled", "cancelled"

    version = models.OneToOneField(ProgramVersion, on_delete=models.CASCADE, related_name="workflow")
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # The stages as they were at the first submission of this chain of versions:
    # [{order, name, assignee_user, assignee_role, due_work_days, resubmit}]
    stages = models.JSONField()
    # The submission this one follows after a return (D54).
    # Several submissions may answer the same return when one of them was withdrawn.
    previous = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="next")
    start_stage = models.PositiveSmallIntegerField()
    # The pre-submit check (task 5.4): the critical findings the author submitted with, and why.
    pre_submit = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.OPEN, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.version} workflow ({self.outcome or 'open'})"


class StageTask(OrganizationScopedModel):
    """One entry of a version into a stage: whose it is, when it is due, and how it ended."""

    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name="tasks")
    stage = models.PositiveSmallIntegerField()
    assignee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    assignee_role = models.CharField(max_length=20, blank=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    entered_at = models.DateTimeField()
    due_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["entered_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["instance"], condition=Q(closed_at__isnull=True), name="workflows_one_open_task"
            )
        ]
        indexes = [models.Index(fields=["organization", "closed_at", "due_at"], name="workflows_task_due")]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def responsible(self):
        """The one person who decides now, if any: the assigned person or whoever claimed the role's task."""
        return self.assignee_user or self.claimed_by

    def __str__(self) -> str:
        return f"{self.instance.version} stage {self.stage}"


class StageDecision(OrganizationScopedModel):
    class Decision(models.TextChoices):
        APPROVE = "approve", "approve"
        RETURN = "return", "return"

    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name="decisions")
    task = models.OneToOneField(StageTask, on_delete=models.PROTECT, related_name="decision")
    stage = models.PositiveSmallIntegerField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.instance.version} stage {self.stage}: {self.decision}"


class Reminder(OrganizationScopedModel):
    """A reminder or escalation sent for a task (spec 4.6, 6.3), so each is sent once. ``skipped`` marks an early
    reminder that was not sent because the due time had already passed when it was first looked at."""

    class Kind(models.TextChoices):
        BEFORE_DUE = "before_due", "before_due"
        AT_DUE = "at_due", "at_due"
        ESCALATION = "escalation", "escalation"

    task = models.ForeignKey(StageTask, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    skipped = models.BooleanField(default=False)
    sent_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["task", "kind"], name="workflows_reminder_once")]

    def __str__(self) -> str:
        return f"{self.task} {self.kind}"
