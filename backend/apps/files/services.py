import hashlib
import re
import uuid

from apps.tenancy.context import current_organization_id

from . import storage
from .models import File

_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


def _key_name(name: str) -> str:
    """The file's name as it appears in its key: letters (any script), digits, dot, dash and underscore."""
    cleaned = _UNSAFE.sub("_", name).strip("._") or "file"
    return cleaned[-120:]


def store(data: bytes, *, name: str, content_type: str, kind: str, actor) -> File:
    """Keeps the bytes in the store under the active organization, then records them. A failure between the two
    leaves at most an object nobody refers to, never a row without its bytes."""
    key = f"{current_organization_id()}/{kind}/{uuid.uuid4().hex}/{_key_name(name)}"
    storage.write(key, data, content_type)
    return File.objects.create(
        kind=kind,
        name=name[:255],
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        key=key,
        created_by=actor,
    )
