"""InputAdapter ABC。

Phase 1: file のみ。Phase 2 で live_audio（macOS + Windows）、Phase 5 で zoom_sdk。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path


class InputAdapter(ABC):
    """入力ソースの共通インターフェース。

    - `acquire(uri)` は録音済み（or DL 済み）のローカル Path を返す
    - `stream()` は PCM バイト列を yield するか、None（バッチのみ）
    - `supports_streaming` はフラグ。Phase 2 の擬似ストリーム実装では False のまま
    """

    supports_streaming: bool = False

    @abstractmethod
    def acquire(self, uri: str) -> Path:
        """uri を解決してローカル Path を返す（ダウンロード/録音含む）。"""

    def stream(self) -> Iterator[bytes] | None:
        """Phase 4+ で真ストリームを返す。Phase 2 は常に None（録音済 WAV を acquire）。"""
        return None

    def cleanup(self) -> None:
        """一時ファイル等の後片付け（既定は no-op）。"""
        return None
