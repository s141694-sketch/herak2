import time
import uuid

import structlog

log = structlog.get_logger("harak2.request")


class RequestLoggingMiddleware:
    """Binds a request id to every log line and emits one structured line per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.path, method=request.method)
        started = time.perf_counter()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        log.info(
            "request",
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            user_id=getattr(getattr(request, "user", None), "pk", None),
        )
        structlog.contextvars.clear_contextvars()
        return response
