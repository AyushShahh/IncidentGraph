"""Unit tests for Stage 3 manifest manager and incremental file freshness diffing."""
from pathlib import Path
from backend.repository.manifest import ManifestManager


def test_manifest_diff_lifecycle(tmp_path: Path):
    """Test initial index, unchanged detection, modification, and deletion detection."""
    manifest_dir = tmp_path / "manifests"
    service_dir = tmp_path / "service_a"
    service_dir.mkdir()

    file1 = service_dir / "app.py"
    file1.write_text("print('hello')", encoding="utf-8")
    file2 = service_dir / "config.json"
    file2.write_text('{"env": "dev"}', encoding="utf-8")

    mgr = ManifestManager(storage_dir=str(manifest_dir))

    # 1. Initial diff: all files added
    current_files = [file1, file2]
    diff1, old_man = mgr.diff_repository("service_a", service_dir, current_files)

    assert len(diff1.added) == 2
    assert len(diff1.modified) == 0
    assert len(diff1.deleted) == 0
    assert old_man is None

    # Save manifest
    f_man1 = mgr.build_file_manifest(file1, service_dir, chunk_count=1, symbol_count=1)
    f_man2 = mgr.build_file_manifest(file2, service_dir, chunk_count=1, symbol_count=0)
    manifest = mgr.create_repository_manifest(
        service_name="service_a",
        service_root=service_dir,
        file_manifests={f_man1.file_path: f_man1, f_man2.file_path: f_man2},
        total_symbols=1,
    )
    mgr.save_manifest(manifest)

    # 2. Second diff with zero changes: all files unchanged
    diff2, old_man2 = mgr.diff_repository("service_a", service_dir, current_files)
    assert not diff2.has_changes
    assert len(diff2.unchanged) == 2
    assert len(diff2.added) == 0
    assert len(diff2.modified) == 0
    assert len(diff2.deleted) == 0

    # 3. Modify one file
    file1.write_text("print('hello world modified')", encoding="utf-8")
    diff3, _ = mgr.diff_repository("service_a", service_dir, current_files)
    assert diff3.has_changes
    assert len(diff3.modified) == 1
    assert diff3.modified[0] == file1
    assert len(diff3.unchanged) == 1

    # 4. Delete one file from current_files list
    diff4, _ = mgr.diff_repository("service_a", service_dir, [file1])
    assert diff4.has_changes
    assert "config.json" in diff4.deleted


def test_manifest_persistence_roundtrip(tmp_path: Path):
    """Test serializing and reloading repository manifest."""
    manifest_dir = tmp_path / "manifests"
    service_dir = tmp_path / "service_b"
    service_dir.mkdir()
    f1 = service_dir / "main.py"
    f1.write_text("a = 1", encoding="utf-8")

    mgr = ManifestManager(storage_dir=str(manifest_dir))
    f_man = mgr.build_file_manifest(f1, service_dir, chunk_count=1, symbol_count=1)
    repo_man = mgr.create_repository_manifest("service_b", service_dir, {f_man.file_path: f_man}, total_symbols=1)

    mgr.save_manifest(repo_man)

    loaded = mgr.load_manifest("service_b")
    assert loaded is not None
    assert loaded.service_name == "service_b"
    assert loaded.file_count == 1
    assert "main.py" in loaded.files
    assert loaded.files["main.py"].sha256_hash == f_man.sha256_hash
