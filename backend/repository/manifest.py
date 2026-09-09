"""Manifest management and incremental index state tracker.

Computes SHA256 fingerprints to identify added, modified, deleted, and untouched
files, minimizing unnecessary parsing and vector embedding operations.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.repository.schemas import FileManifest, RepositoryManifest

logger = get_logger(__name__)


class ManifestDiff:
    """Differences between current filesystem state and stored manifest."""

    def __init__(
        self,
        added: List[Path],
        modified: List[Path],
        deleted: List[str],  # relative paths
        unchanged: List[Path],
    ) -> None:
        self.added = added
        self.modified = modified
        self.deleted = deleted
        self.unchanged = unchanged

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)


class ManifestManager:
    """Manages serialization, loading, and freshness diffing of repository manifests."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        storage_path_str = storage_dir or settings.MANIFESTS_STORAGE_DIR
        self.storage_dir = Path(storage_path_str).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_manifest_path(self, service_name: str) -> Path:
        """Get the filesystem path for a service's manifest JSON."""
        clean_name = service_name.lower().replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{clean_name}_manifest.json"

    def load_manifest(self, service_name: str) -> Optional[RepositoryManifest]:
        """Load an existing repository manifest from disk if available."""
        manifest_path = self.get_manifest_path(service_name)
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RepositoryManifest.model_validate(data)
        except Exception as exc:
            logger.warning("Failed to load manifest for '%s' from %s: %s", service_name, manifest_path, exc)
            return None

    def save_manifest(self, manifest: RepositoryManifest) -> None:
        """Persist repository manifest to disk atomically."""
        manifest_path = self.get_manifest_path(manifest.service_name)
        temp_path = manifest_path.with_suffix(".tmp")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(manifest.model_dump(), f, indent=2)
            temp_path.replace(manifest_path)
            logger.debug("Saved manifest for '%s' (%d files)", manifest.service_name, manifest.file_count)
        except Exception as exc:
            logger.error("Failed saving manifest for '%s': %s", manifest.service_name, exc)
            if temp_path.exists():
                temp_path.unlink()

    def diff_repository(
        self,
        service_name: str,
        service_root: Path,
        current_files: List[Path],
    ) -> Tuple[ManifestDiff, Optional[RepositoryManifest]]:
        """Compare current files against stored manifest to find diffs."""
        existing_manifest = self.load_manifest(service_name)

        if existing_manifest is None:
            # Full initial index
            return ManifestDiff(
                added=current_files,
                modified=[],
                deleted=[],
                unchanged=[],
            ), None

        known_files = existing_manifest.files
        seen_rel_paths: Set[str] = set()

        added: List[Path] = []
        modified: List[Path] = []
        unchanged: List[Path] = []

        for fpath in current_files:
            try:
                rel_path = fpath.relative_to(service_root).as_posix()
            except ValueError:
                rel_path = fpath.name

            seen_rel_paths.add(rel_path)

            current_hash = self.compute_sha256(fpath)
            if rel_path not in known_files:
                added.append(fpath)
            else:
                stored_file = known_files[rel_path]
                if stored_file.sha256_hash != current_hash:
                    modified.append(fpath)
                else:
                    unchanged.append(fpath)

        # Detect deleted files
        deleted = [rel_p for rel_p in known_files if rel_p not in seen_rel_paths]

        diff = ManifestDiff(
            added=added,
            modified=modified,
            deleted=deleted,
            unchanged=unchanged,
        )
        return diff, existing_manifest

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Compute SHA256 hex digest of a file."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as exc:
            logger.warning("Error hashing file %s: %s", file_path, exc)
            return ""

    @staticmethod
    def build_file_manifest(
        file_path: Path,
        service_root: Path,
        chunk_count: int,
        symbol_count: int,
    ) -> FileManifest:
        """Create a FileManifest record for an indexed file."""
        try:
            rel_path = file_path.relative_to(service_root).as_posix()
        except ValueError:
            rel_path = file_path.name

        stat = file_path.stat()
        file_hash = ManifestManager.compute_sha256(file_path)

        return FileManifest(
            file_path=rel_path,
            sha256_hash=file_hash,
            last_modified=stat.st_mtime,
            file_size_bytes=stat.st_size,
            chunk_count=chunk_count,
            symbol_count=symbol_count,
        )

    @staticmethod
    def create_repository_manifest(
        service_name: str,
        service_root: Path,
        file_manifests: Dict[str, FileManifest],
        total_symbols: int,
    ) -> RepositoryManifest:
        """Assemble a complete RepositoryManifest."""
        total_chunks = sum(fm.chunk_count for fm in file_manifests.values())

        return RepositoryManifest(
            service_name=service_name,
            root_path=str(service_root.resolve()),
            last_indexed_at=datetime.now(timezone.utc).isoformat(),
            file_count=len(file_manifests),
            total_chunks=total_chunks,
            total_symbols=total_symbols,
            files=file_manifests,
        )
