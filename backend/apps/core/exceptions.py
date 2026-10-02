"""Uniform JSON error shape: {"error": {"code": ..., "message": ..., "details": ...}}."""

from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def _code_of(exc) -> str:
    if isinstance(exc, exceptions.ValidationError):
        codes = exc.get_codes()
        if isinstance(codes, list) and len(codes) == 1 and isinstance(codes[0], str) and codes[0] != "invalid":
            return codes[0]
        return "validation_error"
    if isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        if isinstance(codes, str):
            return codes
    return getattr(exc, "default_code", "error")


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data
    code = _code_of(exc)
    if isinstance(detail, dict) and set(detail) == {"detail"}:
        message, details = str(detail["detail"]), None
    elif isinstance(detail, dict):
        message, details = "validation_error", detail
    elif isinstance(detail, list) and len(detail) == 1:
        message, details = str(detail[0]), None
    else:
        message, details = str(detail), None
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
