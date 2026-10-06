"""The S3-compatible store (D75): any provider of the S3 API (MinIO in compose, a cloud bucket in production; moto
in tests and local development). Files leave it only through signed links that expire (spec 7.4)."""

from functools import lru_cache
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings


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


def ensure_bucket() -> None:
    """Creates the bucket where the settings allow it (development and tests); production provisions its own."""
    if not settings.FILES_CREATE_BUCKET:
        return
    try:
        _server().head_bucket(Bucket=settings.FILES_BUCKET)
    except ClientError:
        _server().create_bucket(Bucket=settings.FILES_BUCKET)


def write(key: str, data: bytes, content_type: str) -> None:
    _server().put_object(Bucket=settings.FILES_BUCKET, Key=key, Body=data, ContentType=content_type)


def read(key: str) -> bytes:
    return _server().get_object(Bucket=settings.FILES_BUCKET, Key=key)["Body"].read()


def remove(key: str) -> None:
    _server().delete_object(Bucket=settings.FILES_BUCKET, Key=key)


def signed_link(key: str, *, name: str, content_type: str) -> str:
    """A link that downloads the file under its name, valid for FILES_LINK_SECONDS."""
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
