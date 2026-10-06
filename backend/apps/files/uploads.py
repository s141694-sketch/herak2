"""Limits on uploads (D80): a body larger than allowed is refused from its declared length, before Django reads it
to disk, and each person keeps at most so many files an hour (UPLOAD_THROTTLE_RATE)."""

from rest_framework.throttling import UserRateThrottle

# Room for the multipart boundaries and headers around the file itself.
MULTIPART_ALLOWANCE = 64 * 1024


class UploadThrottle(UserRateThrottle):
    """Counts the uploads only: other methods of the same view (removing a logo) are not uploads."""

    scope = "upload"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


def too_long(request, limit: int) -> bool:
    """Whether the request's body is larger than a file of ``limit`` bytes could make it."""
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return True
    return length > limit + MULTIPART_ALLOWANCE
