from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

import build_runtime as builder


def test_download_verifies_cache_and_rejects_corruption(tmp_path: Path) -> None:
    data = b"official artifact"
    target = builder.Target("", "runtime", hashlib.sha256(data).hexdigest(), "")
    archive = tmp_path / "runtime"
    archive.write_bytes(data)
    assert builder.download(target, tmp_path) == archive
    archive.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        builder.download(target, tmp_path)


def test_download_never_caches_unverified_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = builder.Target("", "runtime", "0" * 64, "")
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", Mock(return_value=io.BytesIO(b"bad"))
    )
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        builder.download(target, tmp_path)
    assert not list(tmp_path.iterdir())


def test_download_cleans_partial_file_on_network_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = builder.Target("", "runtime", "0" * 64, "")
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", Mock(side_effect=OSError("network failed"))
    )
    with pytest.raises(OSError, match="network failed"):
        builder.download(target, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../escaped", "/tmp/lo4py-escaped"])
def test_archive_paths_cannot_escape_staging(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "runtime.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo(name)
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Unsafe archive path"):
        builder._extract_tar(archive, tmp_path / "staging")


def test_archive_links_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../outside"
        bundle.addfile(member)
    with pytest.raises(ValueError, match="Unsupported archive entry"):
        builder._extract_tar(archive, tmp_path / "staging")


def test_stale_runtime_is_not_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(builder, "PACKAGE", tmp_path)
    monkeypatch.setattr(
        builder, "get_target", lambda: builder.TARGETS["linux", "x86_64"]
    )
    (tmp_path / "runtime").mkdir()
    with pytest.raises(RuntimeError, match="incomplete or for a different release"):
        builder.build_runtime()
