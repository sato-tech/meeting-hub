"""Google Drive destination のテスト。"""
from __future__ import annotations

import pytest

from core.cassette_schema import GoogleDriveDestination
from core.context import Context
from core.destinations import GoogleDriveDestinationImpl


def test_resolve_folder_id_drive_scheme():
    assert GoogleDriveDestinationImpl._resolve_folder_id("drive-folder://1AbCdEfGhIjKlMnOpQrStUv") == "1AbCdEfGhIjKlMnOpQrStUv"


def test_resolve_folder_id_raw():
    assert GoogleDriveDestinationImpl._resolve_folder_id("1AbCdEfGhIjKlMnOpQrStUv") == "1AbCdEfGhIjKlMnOpQrStUv"


def test_resolve_folder_id_path_returns_none():
    assert GoogleDriveDestinationImpl._resolve_folder_id("/meetings/sales/minutes/") is None


def test_send_skips_when_folder_unresolvable(minimal_cassette, tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/fake.json")
    impl = GoogleDriveDestinationImpl(GoogleDriveDestination(folder_path="/non/id/path/"))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    impl.send(ctx)
    assert any("google_drive" in w for w in ctx.meta.get("warnings", []))


def test_send_without_credentials_raises(minimal_cassette, tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    impl = GoogleDriveDestinationImpl(GoogleDriveDestination(folder_path="drive-folder://abc123"))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    with pytest.raises(EnvironmentError):
        impl.send(ctx)
