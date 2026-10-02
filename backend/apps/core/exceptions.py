"""Uniform JSON error shape: {"error": {"code": ..., "message": ..., "details": ...}}."""

from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data
    code = getattr(exc, "default_code", "error")
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message, details = str(detail["detail"]), None
    elif isinstance(detail, dict):
        message, details = "validation_error", detail
    else:
        message, details = str(detail), None
    if response.status_code == status.HTTP_400_BAD_REQUEST and details:
        code = "validation_error"
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
