from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.competencies.models import FrameworkVersion
from apps.structures.models import TemplateVersion
from apps.structures.serializers import LevelSerializer

from .models import AlignmentLink, Block, Node, Program, ProgramCollaborator, ProgramVersion


def _permissions(serializer, program) -> dict:
    request = serializer.context.get("request")
    membership = getattr(request, "membership", None) if request else None
    if membership is None:
        return {"edit": False, "manage": False, "collaborate": False}
    from . import services

    collaborate = services.can_edit(program, request.user, membership.role)
    return {
        "edit": collaborate,
        "manage": services.can_manage(program, request.user, membership.role),
        "collaborate": collaborate,
    }


class VersionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgramVersion
        fields = ["id", "number", "status", "current_stage", "created_at", "submitted_at", "approved_at"]


class ProgramSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    versions = VersionSummarySerializer(many=True, read_only=True)
    template_version = serializers.PrimaryKeyRelatedField(queryset=TemplateVersion.all_organizations.none())
    framework_version = serializers.PrimaryKeyRelatedField(
        queryset=FrameworkVersion.all_organizations.none(), write_only=True
    )
    targets = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False, default=list)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Program
        fields = [
            "id",
            "title",
            "target_role",
            "status",
            "owner",
            "template_version",
            "framework_version",
            "targets",
            "created_at",
            "versions",
            "permissions",
        ]
        read_only_fields = ["id", "status", "owner", "created_at", "versions", "permissions"]

    def get_permissions(self, program) -> dict:
        return _permissions(self, program)

    def get_fields(self):
        fields = super().get_fields()
        # Querysets are resolved per request so they are scoped to the active organization.
        fields["template_version"].queryset = TemplateVersion.objects.all()
        fields["framework_version"].queryset = FrameworkVersion.objects.all()
        return fields


class ProgramUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = ["title", "target_role"]


class CollaboratorSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_email = serializers.EmailField(write_only=True)

    class Meta:
        model = ProgramCollaborator
        fields = ["id", "user", "user_email", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class VersionDetailSerializer(serializers.ModelSerializer):
    program = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    framework = serializers.SerializerMethodField()
    targets = serializers.SerializerMethodField()
    source_version = serializers.IntegerField(source="source_version.number", default=None, read_only=True)
    permissions = serializers.SerializerMethodField()
    live = serializers.SerializerMethodField()

    class Meta:
        model = ProgramVersion
        fields = [
            "id",
            "permissions",
            "live",
            "program",
            "number",
            "status",
            "current_stage",
            "source_version",
            "template",
            "framework",
            "targets",
            "created_at",
            "submitted_at",
            "approved_at",
        ]

    def get_permissions(self, version) -> dict:
        allowed = _permissions(self, version.program)
        return {**allowed, "edit": allowed["edit"] and version.is_editable}

    def get_live(self, version) -> dict:
        draft = getattr(version, "draft_document", None) if hasattr(version, "draft_document") else None
        if draft is None:
            return {
                "is_live": False,
                "materialized_at": None,
                "last_error": None,
                "last_error_code": None,
                "issues": [],
            }
        return {
            "is_live": True,
            "materialized_at": draft.materialized_at,
            "last_error": draft.last_error or None,
            # The page translates the code; the message is technical and in English.
            "last_error_code": (draft.last_error_code or "document_invalid") if draft.last_error else None,
            "issues": draft.issues,
        }

    def get_program(self, version) -> dict:
        return {"id": version.program_id, "title": version.program.title, "owner_id": version.program.owner_id}

    def get_template(self, version) -> dict:
        template_version = version.program.template_version
        return {
            "id": template_version.pk,
            "name": template_version.template.name,
            "number": template_version.number,
            "levels": LevelSerializer(template_version.levels.all(), many=True).data,
        }

    def get_framework(self, version) -> dict:
        fv = version.framework_version
        return {"id": fv.pk, "name": fv.framework.name, "number": fv.number}

    def get_targets(self, version) -> list[dict]:
        return [
            {
                "id": t.competency_id,
                "code": t.competency.code,
                "title": t.competency.title,
                "competency_key": str(t.competency.competency_key),
            }
            for t in version.targets.select_related("competency")
        ]


class NodeSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(read_only=True)
    parent_key = serializers.UUIDField(source="parent.node_key", read_only=True, default=None)

    class Meta:
        model = Node
        fields = ["id", "node_key", "parent", "parent_key", "level", "order", "title", "deleted"]
        read_only_fields = fields


class BlockSerializer(serializers.ModelSerializer):
    node_key = serializers.UUIDField(source="node.node_key", read_only=True)

    class Meta:
        model = Block
        fields = ["id", "block_key", "node", "node_key", "type", "content", "content_hash", "order", "deleted"]
        read_only_fields = fields


class NodeWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500)
    parent = serializers.IntegerField(required=False, allow_null=True)
    order = serializers.IntegerField(required=False, min_value=0)


class NodeMoveSerializer(serializers.Serializer):
    parent = serializers.IntegerField(allow_null=True)
    order = serializers.IntegerField(min_value=0)


class BlockWriteSerializer(serializers.Serializer):
    node = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False)
    content = serializers.JSONField(required=False)
    order = serializers.IntegerField(required=False, min_value=0)


class AlignmentLinkSerializer(serializers.ModelSerializer):
    source_key = serializers.UUIDField(source="source.block_key", read_only=True)
    target_block_key = serializers.UUIDField(source="target_block.block_key", read_only=True, default=None)
    target_competency_code = serializers.CharField(source="target_competency.code", read_only=True, default=None)

    class Meta:
        model = AlignmentLink
        fields = [
            "id",
            "kind",
            "source",
            "source_key",
            "target_block",
            "target_block_key",
            "target_competency",
            "target_competency_code",
            "created_at",
        ]
        read_only_fields = fields


class AlignmentLinkWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=AlignmentLink.Kind.choices)
    source = serializers.IntegerField()
    target_block = serializers.IntegerField(required=False, allow_null=True)
    target_competency = serializers.IntegerField(required=False, allow_null=True)
