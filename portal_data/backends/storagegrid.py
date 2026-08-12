"""Helper functions for communicating with NetApp StorageGRID."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from django.conf import settings


def get_storagegrid_client() -> Any:  # noqa: ANN401
    """Return a boto3 S3 client configured for NetApp StorageGRID."""
    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGEGRID_ENDPOINT_URL,
        aws_access_key_id=settings.STORAGEGRID_ACCESS_KEY_ID,
        aws_secret_access_key=settings.STORAGEGRID_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "STORAGEGRID_REGION_NAME", "us-east-1"),
        config=Config(signature_version="s3v4"),
    )


def generate_presigned_download_url(
    *,
    bucket: str,
    key: str,
    filename: str | None = None,
    expires_in: int | None = None,
) -> str:
    """Generate a temporary StorageGRID download URL for an object."""
    params: dict[str, str] = {
        "Bucket": bucket,
        "Key": key,
    }

    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    ttl = expires_in or settings.PORTAL_DATA_SIGNED_URL_TTL_SECONDS

    return str(
        get_storagegrid_client().generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=ttl,
        )
    )
