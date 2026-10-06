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


def _shortened(name: str, length: int = 255) -> str:
    """The name cut to ``length`` characters, keeping its extension (a long program title, phase 7 review)."""
    if len(name) <= length:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or len(extension) > 10:
        return name[:length]
    return f"{stem[: length - len(extension) - 1]}.{extension}"


def store(data: bytes, *, name: str, content_type: str, kind: str, actor, version=None) -> File:
    """Keeps the bytes in the store under the active organization, then records them. A failure between the two
    leaves at most an object nobody refers to, never a row without its bytes."""
    key = f"{current_organization_id()}/{kind}/{uuid.uuid4().hex}/{_key_name(name)}"
    storage.write(key, data, content_type)
    return File.objects.create(
        kind=kind,
        name=_shortened(name),
        version=version,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        key=key,
        created_by=actor,
    )
