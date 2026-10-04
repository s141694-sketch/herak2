from rest_framework import serializers

from .models import Finding, ObjectiveAnalysis, QualityReport


class FindingSerializer(serializers.ModelSerializer):
    competency = serializers.SerializerMethodField()
    dismissal = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()

    class Meta:
        model = Finding
        fields = [
            "id",
            "key",
            "kind",
            "severity",
            "source",
            "confidence",
            "node_key",
            "block_key",
            "competency",
            "params",
            "explanation",
            "dismissal",
        ]

    def get_key(self, finding) -> str:
        # Runs recreate findings with new ids; the same finding keeps its source and fingerprint.
        return f"{finding.source}:{finding.fingerprint}"

    def get_competency(self, finding):
        c = finding.competency
        return {"id": c.pk, "key": str(c.competency_key), "code": c.code, "title": c.title} if c else None

    def get_dismissal(self, finding):
        if finding.dismissed_at is None:
            return None
        by = finding.dismissed_by
        return {
            "reason": finding.dismissed_reason,
            "at": finding.dismissed_at,
            "by": {"id": by.pk, "name": by.full_name or by.email} if by else None,
        }


class ObjectiveAnalysisSerializer(serializers.ModelSerializer):
    rule = serializers.SerializerMethodField()
    ai = serializers.SerializerMethodField()

    class Meta:
        model = ObjectiveAnalysis
        fields = ["block_key", "node_key", "text", "verb", "rule", "components", "score", "errors", "dimension", "ai"]

    def get_rule(self, o):
        return {"level_id": o.level_id, "level": o.level, "domain": o.domain or None, "confidence": o.confidence}

    def get_ai(self, o):
        if o.ai_status == "none":
            return None
        return {
            "status": o.ai_status,
            "level_id": o.ai_level_id,
            "domain": o.ai_domain or None,
            "confidence": o.ai_confidence or None,
            "explanation": o.ai_explanation,
        }


class QualityReportSerializer(serializers.ModelSerializer):
    findings = FindingSerializer(many=True, read_only=True)
    objectives = ObjectiveAnalysisSerializer(many=True, read_only=True)
    rollup = serializers.SerializerMethodField()

    class Meta:
        model = QualityReport
        fields = [
            "id",
            "version",
            "status",
            "last_run",
            "rules_version",
            "ai_prompts",
            "ai_models",
            "counts",
            "started_at",
            "finished_at",
            "error",
            "findings",
            "objectives",
            "rollup",
        ]

    def get_rollup(self, report):
        from .services import rollup

        return rollup(report)


class DismissSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, trim_whitespace=True)
