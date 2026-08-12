"""Base types for portal data storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PortalDataFile:
    """File metadata exposed by a portal data backend."""

    name: str
    path: str
    size: int | None = None
    checksum: str | None = None


@dataclass(frozen=True)
class PortalDataset:
    """Dataset metadata exposed by a portal data backend."""

    id: str
    title: str
    datatype: str
    repository: str
    year: int | None
    unit: str | None
    metadata: dict
    files: list[PortalDataFile]


class PortalDataBackend(Protocol):
    """Interface implemented by portal data storage backends."""

    def list_datasets(self, *, datatype: str) -> list[PortalDataset]:
        """Return datasets available for a datatype."""

    def get_dataset(self, dataset_id: str) -> PortalDataset | None:
        """Return one dataset by identifier, if it exists."""

    def get_download_url(
        self,
        *,
        dataset_id: str,
        file_path: str,
        expires_in_seconds: int,
    ) -> str:
        """Return a temporary download URL for a dataset file."""
