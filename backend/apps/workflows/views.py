from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.programs.models import Program, ProgramVersion
from apps.programs.serializers import VersionSummarySerializer
from apps.programs.services import can_edit
from apps.tenancy.permissions import AdminWritesMembersRead, HasActiveOrganization

from . import services
from .models import ProgramWorkflow, StageTask, WorkflowInstance, WorkflowTemplate
from .serializers import StageTaskSerializer, WorkflowInstanceSerializer, WorkflowTemplateSerializer


def _template_body(request) -> dict:
    data = request.data if isinstance(request.data, dict) else {}
    return {
        "name": data.get("name", ""),
        "stages": data.get("stages"),
        "is_default": bool(data.get("is_default", False)),
    }


class WorkflowTemplateListView(generics.ListAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = WorkflowTemplateSerializer

    def get_queryset(self):
        return WorkflowTemplate.objects.all()

    def post(self, request):
        template = services.save_template(None, actor=request.user, **_template_body(request))
        return Response(WorkflowTemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class WorkflowTemplateDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = WorkflowTemplateSerializer

    def get_queryset(self):
        return WorkflowTemplate.objects.all()

    def put(self, request, pk):
        template = services.save_template(self.get_object(), actor=request.user, **_template_body(request))
        return Response(WorkflowTemplateSerializer(template).data)

    def delete(self, request, pk):
        services.delete_template(self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProgramWorkflowView(APIView):
    """The template a program follows: its own choice, or the organization's default."""

    permission_classes = [HasActiveOrganization]

    def _body(self, program):
        choice = ProgramWorkflow.objects.filter(program=program).first()
        template = services.template_for(program)
        return {
            "chosen": choice.template_id if choice else None,
            "template": WorkflowTemplateSerializer(template).data if template else None,
        }

    def get(self, request, pk):
        return Response(self._body(get_object_or_404(Program.objects, pk=pk)))

    def put(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        if not (can_edit(program, request.user, request.membership.role) or request.membership.role == Role.ADMIN):
            raise exceptions.PermissionDenied("only the program's collaborators or an admin choose its workflow")
        if not program.versions.filter(status=ProgramVersion.Status.DRAFT).exists():
            raise services.WorkflowError("the workflow is chosen while the program has a draft", code="not_draft")
        chosen = request.data.get("template") if isinstance(request.data, dict) else None
        template = get_object_or_404(WorkflowTemplate.objects, pk=chosen) if chosen is not None else None
        services.choose_template(program, template, actor=request.user)
        return Response(self._body(Program.objects.get(pk=pk)))


class SubmitVersionView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        reason = request.data.get("reason", "") if isinstance(request.data, dict) else ""
        version = services.submit(version, actor=request.user, role=request.membership.role, reason=str(reason or ""))
        return Response(VersionSummarySerializer(version).data)


class WithdrawVersionView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        version = services.withdraw(version, actor=request.user, role=request.membership.role)
        return Response(VersionSummarySerializer(version).data)


class CancelVersionView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        version = services.cancel(version, actor=request.user, role=request.membership.role)
        return Response(VersionSummarySerializer(version).data)


class VersionWorkflowView(APIView):
    """The version's submission, if it has one: stages, tasks, decisions and the submission it answers."""

    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        instance = WorkflowInstance.objects.filter(version=version).first()
        data = WorkflowInstanceSerializer(instance, context={"request": request}).data if instance else None
        return Response({"submission": data})


def _tasks():
    return StageTask.objects.select_related("assignee_user", "claimed_by", "instance__version__program")


class TaskListView(generics.ListAPIView):
    """The caller's open tasks: assigned to them, or to their role and not taken by someone else. An admin may ask
    for every open task (``?scope=all``) to follow delays."""

    permission_classes = [HasActiveOrganization]
    serializer_class = StageTaskSerializer

    def get_queryset(self):
        user, role = self.request.user, self.request.membership.role
        tasks = _tasks().filter(closed_at__isnull=True).order_by("due_at", "id")
        if self.request.query_params.get("scope") == "all" and role == Role.ADMIN:
            return tasks
        return tasks.filter(
            Q(assignee_user=user)
            | Q(claimed_by=user)
            | (Q(assignee_role=role) & ~Q(assignee_role="") & Q(claimed_by__isnull=True))
        )


class _TaskAction(APIView):
    permission_classes = [HasActiveOrganization]

    def task(self, pk) -> StageTask:
        return get_object_or_404(_tasks(), pk=pk)

    def respond(self, task):
        task = _tasks().get(pk=task.pk)
        return Response(StageTaskSerializer(task, context={"request": self.request}).data)


class ClaimTaskView(_TaskAction):
    def post(self, request, pk):
        return self.respond(services.claim(self.task(pk), actor=request.user, role=request.membership.role))


class ReleaseTaskView(_TaskAction):
    def post(self, request, pk):
        return self.respond(services.release(self.task(pk), actor=request.user, role=request.membership.role))


class DecideTaskView(_TaskAction):
    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        version = services.decide(
            self.task(pk),
            actor=request.user,
            role=request.membership.role,
            decision=str(data.get("decision", "")),
            note=str(data.get("note", "") or ""),
        )
        return Response(VersionSummarySerializer(version).data)
