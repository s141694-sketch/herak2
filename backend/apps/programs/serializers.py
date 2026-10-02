from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.competencies.models import FrameworkVersion
from apps.structures.models import TemplateVersion
from apps.structures.serializers import LevelSerializer

from .models import Program, ProgramCollaborator, ProgramVersion


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
        ]
        read_only_fields = ["id", "status", "owner", "created_at", "versions"]

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

    class Meta:
        model = ProgramVersion
        fields = [
            "id",
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
