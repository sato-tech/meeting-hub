"""FileAdapter のユニットテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.adapters.file import FileAdapter


def test_acquire_local_file(tmp_path: Path) -> None:
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    a = FileAdapter(storage="local")
    assert a.acquire(str(src)) == src


def test_acquire_local_missing_raises(tmp_path: Path) -> None:
    a = FileAdapter(storage="local")
    with pytest.raises(FileNotFoundError):
        a.acquire(str(tmp_path / "nope.mp4"))


def test_extract_file_id_variants() -> None:
    a = FileAdapter(storage="google_drive")
    assert a._extract_file_id("drive://abc123XYZ_-def456789") == "abc123XYZ_-def456789"
    assert a._extract_file_id(
        "https://drive.google.com/file/d/1AbcDefGhIjKlMnOpQrStUv/view"
    ) == "1AbcDefGhIjKlMnOpQrStUv"
    assert a._extract_file_id("1AbcDefGhIjKlMnOpQrStUv") == "1AbcDefGhIjKlMnOpQrStUv"


def test_extract_file_id_invalid() -> None:
    a = FileAdapter(storage="google_drive")
    with pytest.raises(ValueError):
        a._extract_file_id("short")


def test_drive_without_credentials_raises(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    a = FileAdapter(storage="google_drive")
    with pytest.raises(EnvironmentError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        a.acquire("drive://abc123XYZ_-def456789")


def test_unknown_storage_raises() -> None:
    with pytest.raises(ValueError):
        FileAdapter(storage="ftp").acquire("ftp://x")
