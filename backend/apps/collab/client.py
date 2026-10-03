"""Django -> collaboration service calls: freeze, unfreeze, snapshot and lock a live document.

None of them makes the service call back into Django: a freeze or a snapshot answers with the document itself,
so a Django worker never waits on another Django worker (review finding: the old flush could exhaust them).
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class CollabUnavailable(Exception):
    pass


def call(action: str, document: str, *, query: dict | None = None, timeout: float | None = None) -> dict:
    url = f"{settings.COLLAB_INTERNAL_URL}/internal/documents/{urllib.parse.quote(document, safe='')}/{action}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url, method="POST", data=b"", headers={"Authorization": f"Service {settings.COLLAB_SERVICE_SECRET}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout or settings.COLLAB_TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise CollabUnavailable(str(exc)) from exc
