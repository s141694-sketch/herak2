"""Domain errors that map to HTTP 409 with a stable code the client translates."""

from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"
    default_detail = "the request conflicts with the current state"

    def __init__(self, message: str | None = None, code: str | None = None):
        super().__init__(detail=message or self.default_detail, code=code or self.default_code)
