from rest_framework import serializers

from .models import AIPolicy


class AIPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = AIPolicy
        fields = ["mode", "monthly_token_quota"]
