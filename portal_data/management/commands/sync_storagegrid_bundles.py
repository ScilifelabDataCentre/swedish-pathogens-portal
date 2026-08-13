"""Sync portal data bundle manifests from NetApp StorageGRID."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from portal_data.backends.manifests import PortalBundleManifest
from portal_data.backends.storagegrid import S3Client
from portal_data.models import PortalDatasetIndex

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManifestLocation:
    """Location of a discovered manifest in object storage."""

    bucket: str
    key: str

    @property
    def dataset_prefix(self) -> str:
        """Return the prefix containing the manifest and files directory."""
        return self.key.rsplit("/", 1)[0]

    @property
    def uri(self) -> str:
        """Return a human-readable object URI."""
        return f"s3://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class ValidationResult:
    """Validation result for one dataset bundle."""

    manifest: PortalBundleManifest | None
    errors: list[str]
    unexpected_files: list[str]

    @property
    def is_valid(self) -> bool:
        """Return whether the bundle passed validation."""
        return self.manifest is not None and not self.errors


class Command(BaseCommand):
    """Synchronise StorageGRID bundle manifests into PortalDatasetIndex."""

    help = "Sync portal data bundle manifests from NetApp StorageGRID."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register management command arguments."""
        parser.add_argument(
            "--bucket",
            action="append",
            dest="buckets",
            help=(
                "Buckets to scan. Can be provided multiple times. Defaults to settings.S3_BUCKETS."
            ),
        )
        parser.add_argument(
            "--prefix",
            default="",
            help=(
                "Prefix to scan within each bucket. Example: 'units/'. Defaults to the bucket root."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report changes without writing to the database.",
        )
        parser.add_argument(
            "--detect-unexpected-files",
            action="store_true",
            help=(
                "Report files under each dataset prefix that are not listed "
                "in manifest.json. These are warnings by default."
            ),
        )
        parser.add_argument(
            "--unexpected-files-fail",
            action="store_true",
            help=(
                "Treat unexpected files as validation errors. Only meaningful "
                "with --detect-unexpected-files."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of manifests to process. Useful for testing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401
        """Run the synchronisation command."""
        del args

        buckets = options["buckets"] or getattr(settings, "S3_BUCKETS", None)
        prefix = options["prefix"] or ""
        dry_run = bool(options["dry_run"])
        detect_unexpected_files = bool(options["detect_unexpected_files"])
        unexpected_files_fail = bool(options["unexpected_files_fail"])
        limit = options["limit"]

        if not buckets:
            msg = "No buckets configured. Pass --bucket or define settings.S3_BUCKETS."
            raise CommandError(msg)

        if isinstance(buckets, str):
            buckets = [buckets]

        s3_client = S3Client()
        processed = 0
        indexed = 0
        invalid = 0
        failed = 0

        self.stdout.write(
            self.style.NOTICE(
                f"Scanning {len(buckets)} bucket(s), prefix={prefix!r}, dry_run={dry_run}",
            ),
        )

        for bucket in buckets:
            try:
                locations = self._discover_manifests(
                    s3_client=s3_client,
                    bucket=bucket,
                    prefix=prefix,
                )
            except (BotoCoreError, ClientError) as err:
                failed += 1
                logger.exception("Failed to list manifests in bucket %s", bucket)
                self.stderr.write(self.style.ERROR(f"Failed to list {bucket}: {err}"))
                continue

            for location in locations:
                if limit is not None and processed >= limit:
                    break

                processed += 1

                result = self._validate_location(
                    s3_client=s3_client,
                    location=location,
                    detect_unexpected_files=detect_unexpected_files,
                    unexpected_files_fail=unexpected_files_fail,
                )

                if result is None:
                    failed += 1
                    continue

                if result.is_valid:
                    indexed += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"VALID   {location.uri} dataset_id={result.manifest.id}",
                        ),
                    )
                else:
                    invalid += 1
                    dataset_id = self._dataset_id_from_result_or_location(
                        result=result,
                        location=location,
                    )
                    errors = "; ".join(result.errors)
                    self.stdout.write(
                        self.style.WARNING(
                            f"INVALID {location.uri} dataset_id={dataset_id}: {errors}",
                        ),
                    )

                if result.unexpected_files:
                    self.stdout.write(
                        self.style.WARNING(
                            f"UNEXPECTED FILES {location.uri}: "
                            f"{len(result.unexpected_files)} file(s)",
                        ),
                    )

                if not dry_run:
                    self._write_index_row(location=location, result=result)

            if limit is not None and processed >= limit:
                break

        summary = (
            f"Processed={processed}, valid={indexed}, invalid={invalid}, "
            f"failed={failed}, dry_run={dry_run}"
        )

        if failed:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

    def _validate_location(
        self,
        s3_client: S3Client,
        location: ManifestLocation,
        detect_unexpected_files: bool,
        unexpected_files_fail: bool,
    ) -> ValidationResult | None:
        """Validate one location and handle operational failures."""
        try:
            return self._validate_bundle(
                s3_client=s3_client,
                location=location,
                detect_unexpected_files=detect_unexpected_files,
                unexpected_files_fail=unexpected_files_fail,
            )
        except (BotoCoreError, ClientError, json.JSONDecodeError, ValueError) as err:
            logger.exception("Failed to validate %s", location.uri)
            self.stderr.write(self.style.ERROR(f"Failed {location.uri}: {err}"))
            return None

    def _discover_manifests(
        self,
        s3_client: S3Client,
        bucket: str,
        prefix: str | None = None,
    ) -> list[ManifestLocation]:
        """Find all manifest.json objects in a specific bucket and optional prefix."""
        keys = s3_client.list_all_objects(bucket=bucket, prefix=prefix)

        locations: list[ManifestLocation] = []
        for key in keys:
            if key.endswith("/manifest.json") or key == "manifest.json":
                locations.append(ManifestLocation(bucket=bucket, key=key))

        locations.sort(key=lambda location: location.key)
        return locations

    def _validate_bundle(
        self,
        s3_client: S3Client,
        location: ManifestLocation,
        detect_unexpected_files: bool,
        unexpected_files_fail: bool,
    ) -> ValidationResult:
        """Load and validate one manifest and its referenced files."""
        errors: list[str] = []
        unexpected_files: list[str] = []

        manifest_payload = self._read_json_object(
            s3_client=s3_client,
            bucket=location.bucket,
            key=location.key,
        )

        try:
            manifest = PortalBundleManifest.from_dict(manifest_payload)
        except ValueError as err:
            return ValidationResult(
                manifest=None,
                errors=[f"Manifest schema validation failed: {err}"],
                unexpected_files=[],
            )

        if not manifest.files:
            errors.append("Manifest contains no files")

        listed_file_keys = {
            self._file_key(location.dataset_prefix, file_record.path)
            for file_record in manifest.files
        }

        for file_record in manifest.files:
            file_key = self._file_key(location.dataset_prefix, file_record.path)

            object_info = s3_client.head_object(bucket=location.bucket, key=file_key)
            if not object_info:
                errors.append(f"Missing file: {file_record.path}")
                continue

            if file_record.size is not None and object_info.content_length != file_record.size:
                errors.append(
                    "Size mismatch for "
                    f"{file_record.path}: manifest={file_record.size}, "
                    f"actual={object_info.content_length}",
                )

        if detect_unexpected_files:
            actual_file_keys = s3_client.list_all_objects(
                bucket=location.bucket, prefix=location.dataset_prefix
            )

            unexpected_file_keys = sorted(
                set(actual_file_keys) - listed_file_keys - {location.key},
            )

            unexpected_files = [
                key.removeprefix(f"{location.dataset_prefix}/") for key in unexpected_file_keys
            ]

            if unexpected_files and unexpected_files_fail:
                errors.append(
                    "Unexpected files present: " + ", ".join(unexpected_files[:20]),
                )

        return ValidationResult(
            manifest=manifest,
            errors=errors,
            unexpected_files=unexpected_files,
        )

    def _read_json_object(
        self,
        s3_client: S3Client,
        bucket: str,
        key: str,
    ) -> dict[str, Any]:  # noqa: ANN401
        """Read a JSON object from object storage."""
        body = s3_client.download_s3_file_to_str(bucket=bucket, key=key)

        payload = json.loads(body)
        if not isinstance(payload, dict):
            msg = f"Expected JSON object in s3://{bucket}/{key}"
            raise ValueError(msg)

        return payload

    def _file_key(self, dataset_prefix: str, file_path: str) -> str:
        """Build the object key for a file listed in manifest.json."""
        clean_prefix = dataset_prefix.rstrip("/")
        clean_path = file_path.lstrip("/")
        return f"{clean_prefix}/{clean_path}"

    def _dataset_id_from_result_or_location(
        self,
        result: ValidationResult,
        location: ManifestLocation,
    ) -> str:
        """Get a dataset identifier for logging and indexing."""
        if result.manifest is not None:
            return result.manifest.id

        return location.dataset_prefix.rsplit("/", 1)[-1]

    @transaction.atomic
    def _write_index_row(
        self,
        location: ManifestLocation,
        result: ValidationResult,
    ) -> None:
        """Create or update the index row for one manifest."""
        dataset_id = self._dataset_id_from_result_or_location(
            result=result,
            location=location,
        )

        if result.manifest is None:
            PortalDatasetIndex.objects.update_or_create(
                dataset_id=dataset_id,
                defaults={
                    "datatype": "",
                    "repository": "spp-unit-bundles",
                    "unit": "",
                    "bucket": location.bucket,
                    "manifest_key": location.key,
                    "dataset_prefix": location.dataset_prefix,
                    "title": dataset_id,
                    "metadata": {},
                    "files": [],
                    "ingestion_status": PortalDatasetIndex.IngestionStatus.INVALID,
                    "validation_errors": result.errors,
                    "hidden": True,
                    "withdrawn": False,
                    "indexed_at": timezone.now(),
                },
            )
            return

        manifest = result.manifest
        ingestion_status = (
            PortalDatasetIndex.IngestionStatus.IN_SYNC
            if result.is_valid
            else PortalDatasetIndex.IngestionStatus.INVALID
        )

        PortalDatasetIndex.objects.update_or_create(
            dataset_id=manifest.id,
            defaults={
                "datatype": manifest.datatype,
                "repository": manifest.repository,
                "unit": manifest.unit,
                "bucket": location.bucket,
                "manifest_key": location.key,
                "dataset_prefix": location.dataset_prefix,
                "title": manifest.title,
                "year": manifest.year,
                "metadata": self._metadata_from_manifest(manifest),
                "files": [self._file_to_dict(file_record) for file_record in manifest.files],
                "ingestion_status": ingestion_status,
                "validation_errors": result.errors,
                "public": manifest.public,
                "hidden": manifest.hidden or not result.is_valid,
                "withdrawn": manifest.withdrawn,
                "submitted_at": manifest.provenance.submitted_at,
                "indexed_at": timezone.now(),
            },
        )

    def _metadata_from_manifest(self, manifest: PortalBundleManifest) -> dict[str, Any]:  # noqa: ANN401
        """Build JSON metadata stored in the lightweight index."""
        return {
            "pathogen": manifest.pathogen,
            "matrix": manifest.matrix,
            "instrument": manifest.instrument,
            "provenance": {
                "submitted_by": manifest.provenance.submitted_by,
                "submitted_at": manifest.provenance.submitted_at.isoformat(),
                "notes": manifest.provenance.notes,
            },
        }

    def _file_to_dict(self, file_record: Any) -> dict[str, Any]:  # noqa: ANN401
        """Convert a manifest file record into JSON-serialisable data."""
        return {
            "name": file_record.name,
            "path": file_record.path,
            "size": file_record.size,
            "checksum": file_record.checksum,
        }
