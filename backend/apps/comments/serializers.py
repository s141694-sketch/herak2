from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import Comment, CommentReply
from .services import valid_anchor


class ReplySerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = CommentReply
        fields = ["id", "author", "body", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    resolved_by = UserSerializer(read_only=True)
    replies = ReplySerializer(many=True, read_only=True)
    version_number = serializers.IntegerField(source="version.number", read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "version",
            "version_number",
            "block_key",
            "node_key",
            "anchor",
            "quoted",
            "body",
            "category",
            "status",
            "author",
            "created_at",
            "resolved_by",
            "resolved_at",
            "replies",
        ]
        read_only_fields = fields


class CommentWriteSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    block_key = serializers.UUIDField(required=False, allow_null=True)
    node_key = serializers.UUIDField(required=False, allow_null=True)
    anchor = serializers.JSONField(required=False, allow_null=True)
    quoted = serializers.CharField(required=False, allow_blank=True, max_length=2000, trim_whitespace=False)
    body = serializers.CharField(max_length=5000)
    category = serializers.ChoiceField(choices=Comment.Category.choices)

    def validate_anchor(self, value):
        if not valid_anchor(value):
            raise serializers.ValidationError("anchor must hold base64 start and end positions")
        return value
