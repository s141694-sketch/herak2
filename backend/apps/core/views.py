import structlog
from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .negotiation import IgnoreClientContentNegotiation

log = structlog.get_logger("harak2.health")


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - a health check reports anything
        log.warning("health.database_failed", error=str(exc))
        return "error"


def _check_redis() -> str:
    try:
        cache.set("health", "ok", timeout=5)
        return "ok" if cache.get("health") == "ok" else "error"
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_failed", error=str(exc))
        return "error"


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []
    content_negotiation_class = IgnoreClientContentNegotiation

    def get(self, request):
        checks = {"database": _check_database(), "redis": _check_redis()}
        healthy = all(value == "ok" for value in checks.values())
        return Response({"status": "ok" if healthy else "error", "checks": checks}, status=200 if healthy else 503)
