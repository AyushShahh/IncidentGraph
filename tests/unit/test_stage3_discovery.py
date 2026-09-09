"""Unit tests for Stage 3 dynamic service discovery and filesystem scanning."""
from pathlib import Path
import pytest
from backend.repository.discovery import RepositoryDiscovery, IGNORED_DIRS


def test_discovery_on_services_directory(tmp_path: Path):
    """Test dynamic discovery of microservices in a root directory."""
    # Create fake services
    svc1 = tmp_path / "orders"
    svc1.mkdir()
    (svc1 / "main.py").write_text("def create_order(): pass", encoding="utf-8")
    (svc1 / "README.md").write_text("# Orders Service", encoding="utf-8")

    svc2 = tmp_path / "payments"
    svc2.mkdir()
    (svc2 / "service.py").write_text("def charge(): pass", encoding="utf-8")

    # Create standard ignored directories
    (tmp_path / ".git").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "venv").mkdir()

    discovery = RepositoryDiscovery(root_dirs=str(tmp_path))
    discovered = discovery.discover()

    # orders and payments should be discovered
    assert "orders" in discovered
    assert "payments" in discovered

    # .git, venv, and __pycache__ must NOT be treated as services
    assert ".git" not in discovered
    assert "__pycache__" not in discovered
    assert "venv" not in discovered


def test_discovery_arbitrary_external_service(tmp_path: Path):
    """Test discovering arbitrary external services outside standard directory."""
    ext_svc = tmp_path / "custom_billing_engine"
    ext_svc.mkdir()
    (ext_svc / "app.py").write_text("def process(): pass", encoding="utf-8")

    discovery = RepositoryDiscovery(root_dirs=[])
    discovery.register_service("custom_billing", ext_svc)
    discovered = discovery.discover()

    assert "custom_billing" in discovered
    assert discovered["custom_billing"] == ext_svc.resolve()


def test_scan_repository_files(tmp_path: Path):
    """Test recursive file scanning filtering out ignored directories."""
    svc_dir = tmp_path / "inventory"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("x = 1", encoding="utf-8")
    (svc_dir / "README.md").write_text("# Readme", encoding="utf-8")
    (svc_dir / "Dockerfile").write_text("FROM python", encoding="utf-8")

    sub = svc_dir / "models"
    sub.mkdir()
    (sub / "item.py").write_text("class Item: pass", encoding="utf-8")

    pycache = svc_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-311.pyc").write_bytes(b"dummy")

    files = RepositoryDiscovery.scan_repository_files(svc_dir)
    file_names = {f.name for f in files}

    assert "main.py" in file_names
    assert "README.md" in file_names
    assert "Dockerfile" in file_names
    assert "item.py" in file_names
    assert "main.cpython-311.pyc" not in file_names
