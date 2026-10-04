from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer

from .models import StageDecision, StageTask, WorkflowInstance, WorkflowTemplate


def _users(ids) -> dict[int, dict]:
    return {u.pk: UserSerializer(u).data for u in User.objects.filter(pk__in=[i for i in ids if i])}


class WorkflowTemplateSerializer(serializers.ModelSerializer):
    stages = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowTemplate
        fields = ["id", "name", "is_default", "stages", "created_at", "updated_at"]

    def get_stages(self, template):
        stages = list(template.stages.order_by("order"))
        users = _users(s.assignee_user_id for s in stages)
        return [
            {
                "order": s.order,
                "name": s.name,
                "assignee_user": users.get(s.assignee_user_id),
                "assignee_role": s.assignee_role,
                "due_work_days": s.due_work_days,
                "resubmit": s.resubmit,
            }
            for s in stages
        ]


def task_permissions(task: StageTask, user, role: str) -> dict:
    is_open = task.closed_at is None
    return {
        "can_claim": is_open and bool(task.assignee_role) and task.assignee_role == role and task.claimed_by_id is None,
        "can_release": is_open
        and task.claimed_by_id is not None
        and (task.claimed_by_id == user.pk or role == "admin"),
        "can_decide": is_open and task.responsible() == user,
    }


class StageTaskSerializer(serializers.ModelSerializer):
    assignee_user = UserSerializer(read_only=True)
    claimed_by = UserSerializer(read_only=True)
    stage_name = serializers.SerializerMethodField()
    stage_count = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = StageTask
        fields = [
            "id",
            "stage",
            "stage_name",
            "stage_count",
            "assignee_user",
            "assignee_role",
            "claimed_by",
            "claimed_at",
            "entered_at",
            "due_at",
            "overdue",
            "closed_at",
            "outcome",
            "version",
            "permissions",
        ]

    def get_stage_name(self, task):
        return task.instance.stages[task.stage - 1]["name"]

    def get_stage_count(self, task):
        return len(task.instance.stages)

    def get_overdue(self, task):
        return task.closed_at is None and task.due_at < timezone.now()

    def get_version(self, task):
        version = task.instance.version
        return {
            "id": version.pk,
            "number": version.number,
            "program": {"id": version.program_id, "title": version.program.title},
        }

    def get_permissions(self, task):
        request = self.context.get("request")
        if request is None:
            return {}
        return task_permissions(task, request.user, request.membership.role)


class StageDecisionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = StageDecision
        fields = ["id", "stage", "user", "decision", "note", "created_at"]


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    stages = serializers.SerializerMethodField()
    submitted_by = UserSerializer(read_only=True)
    tasks = serializers.SerializerMethodField()
    decisions = serializers.SerializerMethodField()
    previous = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowInstance
        fields = [
            "id",
            "version",
            "stages",
            "start_stage",
            "pre_submit",
            "submitted_by",
            "created_at",
            "outcome",
            "closed_at",
            "tasks",
            "decisions",
            "previous",
        ]

    def get_stages(self, instance):
        users = _users(s["assignee_user"] for s in instance.stages)
        return [{**s, "assignee_user": users.get(s["assignee_user"])} for s in instance.stages]

    def get_tasks(self, instance):
        tasks = instance.tasks.select_related("assignee_user", "claimed_by", "instance__version__program")
        return StageTaskSerializer(tasks, many=True, context=self.context).data

    def get_decisions(self, instance):
        return StageDecisionSerializer(instance.decisions.select_related("user"), many=True).data

    def get_previous(self, instance):
        # The submission this one answers: what was decided on it, so the reviewer sees why it came back.
        previous = instance.previous
        if previous is None:
            return None
        return {
            "version": {"id": previous.version_id, "number": previous.version.number},
            "decisions": StageDecisionSerializer(previous.decisions.select_related("user"), many=True).data,
        }
