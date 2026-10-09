"""Where files are kept, chosen by FILES_BACKEND.

- "s3" (D75): any provider of the S3 API (a cloud bucket in production; moto in tests and local development).
- "local" (D98): a folder on the server itself, FILES_LOCAL_DIR (a compose volume), for a deployment without a
  bucket. Harak then signs the download links itself.

Either way, files leave the store only through signed links that expire (spec 7.4), given after the API checked who
asks."""

import os
import tempfile
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.core import signing
from django.urls import reverse

LINK_SALT = "harak2.files.link"


def _local() -> bool:
    return settings.FILES_BACKEND == "local"


def _path(key: str) -> Path:
    """The key's place in the folder; a key that would reach outside it is refused."""
    root = Path(settings.FILES_LOCAL_DIR).resolve()
    if not key or key.startswith("/") or "\\" in key:
        raise ValueError(f"not a file key: {key!r}")
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError(f"not a file key: {key!r}")
    return path


@lru_cache(maxsize=4)
def _client(endpoint: str, access_key: str, secret_key: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=access_key or None,
        aws_secret_access_key=secret_key or None,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )


def _server():
    return _client(
        settings.FILES_ENDPOINT_URL,
        settings.FILES_ACCESS_KEY_ID,
        settings.FILES_SECRET_ACCESS_KEY,
        settings.FILES_REGION,
    )


def _public():
    """Links are signed for the address browsers use, which may differ from the one this server uses (compose)."""
    return _client(
        settings.FILES_PUBLIC_ENDPOINT_URL or settings.FILES_ENDPOINT_URL,
        settings.FILES_ACCESS_KEY_ID,
        settings.FILES_SECRET_ACCESS_KEY,
        settings.FILES_REGION,
    )


# Buckets known to exist in this process.
_ready: set[str] = set()


def ensure_bucket() -> None:
    """Creates the bucket where the settings allow it (development and tests, whose stores start empty); production
    provisions its own."""
    if not settings.FILES_CREATE_BUCKET or settings.FILES_BUCKET in _ready:
        return
    try:
        _server().head_bucket(Bucket=settings.FILES_BUCKET)
    except ClientError:
        _server().create_bucket(Bucket=settings.FILES_BUCKET)
    _ready.add(settings.FILES_BUCKET)


def write(key: str, data: bytes, content_type: str) -> None:
    if _local():
        path = _path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Whole or not at all: written beside it, then renamed into place.
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".part-")
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
        return
    ensure_bucket()
    _server().put_object(Bucket=settings.FILES_BUCKET, Key=key, Body=data, ContentType=content_type)


def read(key: str) -> bytes:
    if _local():
        return _path(key).read_bytes()
    return _server().get_object(Bucket=settings.FILES_BUCKET, Key=key)["Body"].read()


def remove(key: str) -> None:
    if _local():
        _path(key).unlink(missing_ok=True)
        return
    _server().delete_object(Bucket=settings.FILES_BUCKET, Key=key)


def keys() -> Iterator[str]:
    """Every stored file's key (backups)."""
    if _local():
        root = Path(settings.FILES_LOCAL_DIR).resolve()
        if not root.exists():
            return
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.name.startswith(".part-"):
                yield path.relative_to(root).as_posix()
        return
    try:
        pages = list(_server().get_paginator("list_objects_v2").paginate(Bucket=settings.FILES_BUCKET))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
            return  # nothing stored yet
        raise
    for page in pages:
        for item in page.get("Contents", []):
            yield item["Key"]


def open_signed(token: str) -> tuple[Path, str, str]:
    """The file a link of the local store names, with its name and type; signing.BadSignature (expired or changed)
    or FileNotFoundError otherwise."""
    data = signing.loads(token, salt=LINK_SALT, max_age=settings.FILES_LINK_SECONDS)
    path = _path(data["k"])
    if not path.is_file():
        raise FileNotFoundError(data["k"])
    return path, data["n"], data["t"]


def signed_link(key: str, *, name: str, content_type: str) -> str:
    """A link that downloads the file under its name, valid for FILES_LINK_SECONDS."""
    if _local():
        token = signing.dumps({"k": key, "n": name, "t": content_type}, salt=LINK_SALT, compress=True)
        return reverse("file-content", args=[token])
    disposition = f"attachment; filename*=UTF-8''{quote(name)}"
    return _public().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.FILES_BUCKET,
            "Key": key,
            "ResponseContentDisposition": disposition,
            "ResponseContentType": content_type,
        },
        ExpiresIn=settings.FILES_LINK_SECONDS,
    )
