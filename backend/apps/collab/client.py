"""Django -> collaboration service calls (flush before submission, lock after)."""

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class CollabUnavailable(Exception):
    pass


def call(action: str, document: str) -> dict:
    url = f"{settings.COLLAB_INTERNAL_URL}/internal/documents/{urllib.parse.quote(document, safe='')}/{action}"
    request = urllib.request.Request(
        url, method="POST", data=b"", headers={"Authorization": f"Service {settings.COLLAB_SERVICE_SECRET}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.COLLAB_TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise CollabUnavailable(str(exc)) from exc
