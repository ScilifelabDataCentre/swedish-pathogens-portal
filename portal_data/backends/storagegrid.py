"""Contains an S3Client class that wraps boto3's S3 client.

Provide a simple interface for interacting with S3-compatible object stores, like
NetApp StorageGRID (deployed) and MinIO (local development).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.utils import timezone


@dataclass
class S3HeadObjectData:
    """Represents the response metadata for an S3 HEAD request operation."""

    content_length: int
    content_type: str
    last_modified: datetime
    etag: str


@dataclass
class S3PresignedUrlData:
    """Represents a presigned URL for an object inside S3."""

    url: str
    expiry: datetime


class S3Client:
    """A wrapper around a boto3 S3 client to enable easy operations with S3."""

    def __init__(self) -> None:
        """Initialize the S3 client."""
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )

    def head_object(self, bucket: str, key: str) -> S3HeadObjectData | None:
        """Return the object's metadata, or None if it doesn't exist."""
        try:
            response = self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            raise

        return S3HeadObjectData(
            content_length=response["ContentLength"],
            content_type=response["ContentType"],
            last_modified=response["LastModified"],
            etag=response["ETag"],
        )

    def list_all_objects(self, bucket: str, prefix: str | None = None) -> list[str]:
        """Return a list of all object keys in a bucket with the given prefix.

        Paginates through all objects in the bucket before returning the list of keys.
        """
        paginator = self.client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        object_keys: list[str] = []
        for page in page_iterator:
            if "Contents" in page:
                object_keys.extend(obj["Key"] for obj in page["Contents"])
        return object_keys

    def download_s3_file_to_str(self, bucket: str, key: str) -> str:
        """Return the file contents of an object in an S3 bucket as a string."""
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        filename: str | None = None,
        time_to_live_seconds: int | None = None,
    ) -> S3PresignedUrlData:
        """Generate a pre-signed URL for an object stored in S3."""
        params: dict[str, str] = {
            "Bucket": bucket,
            "Key": key,
        }
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        expires_in = time_to_live_seconds or settings.S3_PRE_SIGNED_URL_TTL_SECONDS
        presigned_url = self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        expiry = timezone.now() + timedelta(seconds=expires_in)
        return S3PresignedUrlData(url=presigned_url, expiry=expiry)
