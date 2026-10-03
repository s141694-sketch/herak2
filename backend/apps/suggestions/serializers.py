from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.agents.importing import MAX_TEXT_CHARS

from .models import Suggestion


class SuggestionSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    decided_by = UserSerializer(read_only=True)
    original = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()

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

    def get_result(self, suggestion) -> dict | None:
        # An answer Harak's rules refused is kept for the record, never shown (spec 5.1.3).
        return suggestion.result if suggestion.status in Suggestion.SHOWN else None


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
