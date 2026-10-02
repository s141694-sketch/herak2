from rest_framework import serializers

from .models import Level, StructureTemplate, TemplateVersion


class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ["depth", "name_ar", "name_en"]
        read_only_fields = ["depth"]


class TemplateVersionSummarySerializer(serializers.ModelSerializer):
    level_count = serializers.IntegerField(source="levels.count", read_only=True)

    class Meta:
        model = TemplateVersion
        fields = ["id", "number", "status", "published_at", "level_count"]


class TemplateVersionDetailSerializer(serializers.ModelSerializer):
    template = serializers.SerializerMethodField()
    levels = LevelSerializer(many=True, read_only=True)

    class Meta:
        model = TemplateVersion
        fields = ["id", "template", "number", "status", "published_at", "levels"]

    def get_template(self, version) -> dict:
        return {"id": version.template_id, "name": version.template.name}


class TemplateSerializer(serializers.ModelSerializer):
    versions = TemplateVersionSummarySerializer(many=True, read_only=True)
    levels = LevelSerializer(many=True, write_only=True, required=True)

    class Meta:
        model = StructureTemplate
        fields = ["id", "name", "created_at", "versions", "levels"]
        read_only_fields = ["id", "created_at", "versions"]
