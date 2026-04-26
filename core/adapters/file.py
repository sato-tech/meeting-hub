"""FileAdapter — ローカル / Google Drive 両対応（Phase 1）。

Google Drive はサービスアカウント認証（§12-5 RESOLVED）。
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from core.adapters.base import InputAdapter

logger = logging.getLogger(__name__)


class FileAdapter(InputAdapter):
    """ファイル入力。`storage=local` か `storage=google_drive` を受け取る。"""

    DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    # e.g. "drive://<file_id>" or a bare google drive share URL
    _DRIVE_URI = re.compile(r"^drive://(?P<id>[A-Za-z0-9_-]+)$")
    _DRIVE_URL = re.compile(r"drive\.google\.com/.*?/d/(?P<id>[A-Za-z0-9_-]+)")

    def __init__(self, storage: str = "local"):
        self.storage = storage
        self._tmp_files: list[Path] = []

    def acquire(self, uri: str) -> Path:
        if self.storage == "local":
            return self._resolve_local(uri)
        if self.storage == "google_drive":
            return self._download_from_drive(uri)
        raise ValueError(f"Unknown storage: {self.storage}")

    def cleanup(self) -> None:
        for p in self._tmp_files:
            try:
                p.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("Failed to remove tmp file %s: %s", p, e)
        self._tmp_files.clear()

    # ── 内部 ────────────────────────────────
    def _resolve_local(self, uri: str) -> Path:
        p = Path(uri).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
        if not p.is_file():
            raise ValueError(f"Input path is not a file: {p}")
        return p

    def _download_from_drive(self, uri: str) -> Path:
        """サービスアカウントで Drive からダウンロード。

        許容 URI:
          - drive://<fileId>
          - https://drive.google.com/file/d/<fileId>/view?usp=...
          - <fileId> 単独
        """
        file_id = self._extract_file_id(uri)
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path:
            raise EnvironmentError(
                "GOOGLE_APPLICATION_CREDENTIALS is not set. "
                "Configure service account JSON path for storage=google_drive."
            )

        # 遅延 import（Phase 1 依存を optional 扱いにする余地を残す）
        from google.oauth2 import service_account  # type: ignore[import-not-found]
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-not-found]

        creds = service_account.Credentials.from_service_account_file(
            cred_path, scopes=self.DRIVE_SCOPES
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        meta = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
        logger.info(
            "Drive DL: id=%s name=%s mime=%s size=%s",
            file_id, meta.get("name"), meta.get("mimeType"), meta.get("size"),
        )

        suffix = Path(meta.get("name", "download.bin")).suffix or ".bin"
        tmp = Path(tempfile.mkstemp(prefix="mh_drive_", suffix=suffix)[1])
        self._tmp_files.append(tmp)

        request = service.files().get_media(fileId=file_id)
        with tmp.open("wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
        logger.info("Drive DL: saved to %s", tmp)
        return tmp

    def _extract_file_id(self, uri: str) -> str:
        m = self._DRIVE_URI.match(uri)
        if m:
            return m.group("id")
        m = self._DRIVE_URL.search(uri)
        if m:
            return m.group("id")
        if re.fullmatch(r"[A-Za-z0-9_-]{20,}", uri):
            return uri
        raise ValueError(f"Cannot extract Google Drive file ID from: {uri!r}")
