from rest_framework import serializers

from .models import Competency, CompetencyFramework, FrameworkVersion


class CompetencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Competency
        fields = ["id", "competency_key", "code", "title", "description", "level", "requirement", "order"]
        read_only_fields = ["id", "competency_key"]

    def validate_code(self, value: str) -> str:
        value = value.strip()
        version = self.context["version"]
        clash = version.competencies.filter(code=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("this code is already used in this version", code="duplicate_code")
        return value


class VersionSummarySerializer(serializers.ModelSerializer):
    competency_count = serializers.IntegerField(source="competencies.count", read_only=True)

    class Meta:
        model = FrameworkVersion
        fields = ["id", "number", "status", "published_at", "competency_count"]


class FrameworkSerializer(serializers.ModelSerializer):
    versions = VersionSummarySerializer(many=True, read_only=True)

    class Meta:
        model = CompetencyFramework
        fields = ["id", "name", "description", "created_at", "versions"]
        read_only_fields = ["id", "created_at", "versions"]


class FrameworkVersionDetailSerializer(serializers.ModelSerializer):
    framework = serializers.SerializerMethodField()
    competencies = CompetencySerializer(many=True, read_only=True)
    published_by = serializers.EmailField(source="published_by.email", read_only=True, default=None)

    class Meta:
        model = FrameworkVersion
        fields = ["id", "framework", "number", "status", "published_at", "published_by", "competencies"]

    def get_framework(self, version) -> dict:
        return {"id": version.framework_id, "name": version.framework.name}
