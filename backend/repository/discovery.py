"""Service repository discovery and filesystem scanning engine.

Completely dynamic and domain-agnostic: discovers any service repository located
in configured root paths without hardcoding service names.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Standard directory names to exclude from source discovery
IGNORED_DIRS: Set[str] = {
    ".git",
    ".github",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "site-packages",
    "dist",
    "build",
    "egg-info",
    ".idea",
    ".vscode"
}

# File extensions recognized for indexing and retrieval
INDEXABLE_EXTENSIONS: Set[str] = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".dockerfile",
}

# Special filename matches (case-insensitive)
INDEXABLE_FILENAMES: Set[str] = {
    "dockerfile",
    "makefile",
    "requirements.txt",
    "pyproject.toml",
    "readme.md",
}


class RepositoryDiscovery:
    """Discovers and catalogs microservice repositories dynamically."""

    def __init__(self, root_dirs: Optional[List[str] | str] = None) -> None:
        if root_dirs is None:
            raw_roots = settings.REPOSITORIES_ROOT_DIR
        else:
            raw_roots = root_dirs

        if isinstance(raw_roots, str):
            self.root_dirs = [p.strip() for p in raw_roots.split(",") if p.strip()]
        else:
            self.root_dirs = list(raw_roots)

        # Dynamic registry: service_name -> Path
        self._registered_services: Dict[str, Path] = {}

    def discover(self, extra_paths: Optional[List[str]] = None) -> Dict[str, Path]:
        """Scan configured root paths and return discovered service repositories.

        Returns:
            Dict mapping service_name to resolved Path.
        """
        discovered: Dict[str, Path] = {}

        roots_to_scan = list(self.root_dirs)
        if extra_paths:
            roots_to_scan.extend(extra_paths)

        for root_str in roots_to_scan:
            root_path = Path(root_str).resolve()
            if not root_path.exists():
                # Check relative to working directory or project root
                alt_path = Path.cwd() / root_str
                if alt_path.exists():
                    root_path = alt_path.resolve()
                else:
                    logger.debug("Repository root path does not exist: %s", root_str)
                    continue

            if not root_path.is_dir():
                continue

            # Check if root_path itself is a single service repository
            if self._is_service_directory(root_path):
                # If it doesn't contain child service directories, treat as a service
                child_services = [
                    d for d in root_path.iterdir()
                    if d.is_dir() and d.name not in IGNORED_DIRS and self._is_service_directory(d)
                ]
                if not child_services:
                    service_name = root_path.name.lower()
                    discovered[service_name] = root_path
                    continue

            # Scan child subdirectories as independent service repositories
            for child in root_path.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name in IGNORED_DIRS:
                    continue

                if self._is_service_directory(child):
                    service_name = child.name.lower()
                    discovered[service_name] = child
                    logger.debug("Discovered service repository '%s' at %s", service_name, child)

        # Merge any explicitly registered services
        for name, path in self._registered_services.items():
            discovered[name] = path

        logger.info(
            "Service discovery completed: %d services discovered (%s)",
            len(discovered),
            list(discovered.keys()),
        )
        return discovered

    def register_service(self, service_name: str, path: Path | str) -> None:
        """Register an arbitrary external service repository path dynamically."""
        p = Path(path).resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Invalid service path: {p}")
        self._registered_services[service_name.lower()] = p

    @staticmethod
    def _is_service_directory(directory: Path) -> bool:
        """Heuristic to determine if a directory qualifies as a code repository."""
        if directory.name in IGNORED_DIRS or directory.name.startswith("."):
            return False

        # If it has python files or dockerfile or pyproject/requirements
        for item in directory.iterdir():
            if item.is_file():
                if item.suffix.lower() in INDEXABLE_EXTENSIONS:
                    return True
                if item.name.lower() in INDEXABLE_FILENAMES:
                    return True
            elif item.is_dir() and item.name not in IGNORED_DIRS and not item.name.startswith("."):
                # Check 1 level deep for python files
                for sub in item.iterdir():
                    if sub.is_file() and sub.suffix.lower() == ".py":
                        return True
        return False

    @staticmethod
    def scan_repository_files(service_root: Path) -> List[Path]:
        """Recursively discover all indexable files within a service repository.

        Args:
            service_root: Root directory of the service.

        Returns:
            Sorted list of resolved indexable file paths.
        """
        valid_files: List[Path] = []

        for root, dirs, files in os.walk(service_root):
            # Modify dirs in-place to prevent traversing ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]

            for file_name in files:
                if file_name.startswith("."):
                    continue

                fpath = Path(root) / file_name
                ext = fpath.suffix.lower()
                fname_lower = file_name.lower()

                if ext in INDEXABLE_EXTENSIONS or fname_lower in INDEXABLE_FILENAMES:
                    valid_files.append(fpath.resolve())

        valid_files.sort()
        return valid_files

    @staticmethod
    def get_relative_path(file_path: Path, service_root: Path) -> str:
        """Return a POSIX relative path string from service root."""
        try:
            return file_path.relative_to(service_root).as_posix()
        except ValueError:
            return file_path.name
