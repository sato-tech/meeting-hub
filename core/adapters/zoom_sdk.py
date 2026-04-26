"""ZoomSDKAdapter — Zoom Meeting SDK Raw Data アダプタ（**Phase 5 で保留**）。

現状ステータス（2026-04-23）:
  - ROADMAP §Phase 5 で「optional」扱い
  - Zoom Marketplace 開発者登録の社内承認待ち
  - Zoom 有料プランの SDK 利用条件確認待ち
  - Python バインディングの OSS 状況調査未了

本ファイルは skeleton として配置し、`acquire()` で必ず NotImplementedError を投げる。
実装を再開する場合は `docs/SETUP_ZOOM_SDK.md` の「復活条件」の項目を満たした上で
本ファイルを置き換える。

代替策:
  - Zoom 会議の音声は OS レベルで `LiveAudioAdapter`（BlackHole/VB-Cable）で取得可能
  - 話者分離は channel_based（Ch1=self, Ch2=system）or pyannote で代替
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from core.adapters.base import InputAdapter

logger = logging.getLogger(__name__)


ZOOM_SDK_DEFERRAL_MESSAGE = (
    "ZoomSDKAdapter is pending social/compliance approval and is not implemented. "
    "Use `LiveAudioAdapter` (BlackHole on macOS / VB-Cable on Windows) instead. "
    "See docs/SETUP_ZOOM_SDK.md for reactivation conditions."
)


class ZoomSDKAdapter(InputAdapter):
    """Zoom Meeting SDK の Raw Data（音声チャンク）を取得するアダプタ。

    **未実装**: `acquire()` と `stream()` は NotImplementedError を投げる。
    `cassette.input.type=zoom_sdk` を使う場合は必ず skeleton 状態であることを確認する。

    設計（将来の実装メモ）:
      - `supports_streaming = True`（真ストリーム、PCM frames を yield）
      - Zoom SDK が meeting.audio.raw_data callback で渡してくる PCM を Queue に push
      - `source_preference=[zoom_sdk, system_audio]` でフォールバックを提示（cassette schema）
    """

    supports_streaming = True

    def __init__(self, *, meeting_id: str | None = None, sdk_key: str | None = None, sdk_secret: str | None = None):
        self.meeting_id = meeting_id
        self.sdk_key = sdk_key
        self.sdk_secret = sdk_secret

    def acquire(self, uri: str) -> Path:
        logger.warning(ZOOM_SDK_DEFERRAL_MESSAGE)
        raise NotImplementedError(ZOOM_SDK_DEFERRAL_MESSAGE)

    def stream(self) -> Iterator[bytes] | None:
        raise NotImplementedError(ZOOM_SDK_DEFERRAL_MESSAGE)

    def cleanup(self) -> None:
        return None
