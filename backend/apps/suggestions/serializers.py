from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.agents.importing import MAX_TEXT_CHARS
from apps.quality.ai_layer import rules_only

from .models import Suggestion
from .services import ai_hidden


class SuggestionSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    decided_by = UserSerializer(read_only=True)
    original = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()

    class Meta:
        model = Suggestion
        fields = [
            "id",
            "version",
            "kind",
            "subject",
            "status",
            "reason",
            "original",
            "result",
            "model",
            "prompt_version",
            "requested_by",
            "created_at",
            "finished_at",
            "decided_by",
            "decided_at",
            "decision_reason",
        ]

    def get_original(self, suggestion) -> str | None:
        return suggestion.request.get("objective") if suggestion.kind == Suggestion.Kind.REWRITE else None

    def _hidden(self, suggestion) -> bool:
        cache = self.context.setdefault("_rules_only", {})
        if suggestion.pk not in cache:
            cache[suggestion.pk] = ai_hidden(suggestion)
        return cache[suggestion.pk]

    def get_status(self, suggestion) -> str:
        # In rules-only mode an open AI suggestion reads as failed for that reason: it can no longer be applied.
        if suggestion.status in Suggestion.OPEN and self._hidden(suggestion):
            return Suggestion.Status.FAILED
        return suggestion.status

    def get_reason(self, suggestion) -> str:
        if suggestion.status in Suggestion.OPEN and self._hidden(suggestion):
            return "rules_only"
        if (
            suggestion.kind == Suggestion.Kind.IMPORT
            and suggestion.status in Suggestion.OPEN
            and rules_only(suggestion.organization_id)
        ):
            return "rules_only"
        return suggestion.reason

    def get_result(self, suggestion) -> dict | None:
        # An answer Harak's rules refused is kept for the record, never shown (spec 5.1.3); nor is any AI result
        # in rules-only mode, where an import shows the rules' layout.
        if suggestion.status not in Suggestion.SHOWN or self._hidden(suggestion):
            return None
        if suggestion.kind == Suggestion.Kind.IMPORT and suggestion.result.get("source") == "ai":
            if rules_only(suggestion.organization_id):
                return suggestion.request.get("rules")
        return suggestion.result


class SuggestionRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Suggestion.Kind.choices)
    block_key = serializers.UUIDField(required=False)
    text = serializers.CharField(required=False, max_length=MAX_TEXT_CHARS, trim_whitespace=False)

    def validate(self, data):
        if data["kind"] == Suggestion.Kind.REWRITE and "block_key" not in data:
            raise serializers.ValidationError({"block_key": "say which objective to rewrite"})
        if data["kind"] == Suggestion.Kind.IMPORT and not data.get("text", "").strip():
            raise serializers.ValidationError({"text": "paste the text to import"})
        return data


class DismissSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
