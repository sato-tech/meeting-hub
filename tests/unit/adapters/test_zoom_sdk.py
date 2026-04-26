"""ZoomSDKAdapter は Phase 5 で skeleton のみ。必ず NotImplementedError を投げる。"""
from __future__ import annotations

import pytest

from core.adapters.zoom_sdk import ZOOM_SDK_DEFERRAL_MESSAGE, ZoomSDKAdapter


def test_acquire_raises_not_implemented():
    a = ZoomSDKAdapter(meeting_id="123")
    with pytest.raises(NotImplementedError, match="pending social/compliance"):
        a.acquire("zoom://123")


def test_stream_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        ZoomSDKAdapter().stream()


def test_deferral_message_is_informative():
    # 利用者が対応策を知れるよう、メッセージに LiveAudioAdapter や docs への言及がある
    assert "LiveAudioAdapter" in ZOOM_SDK_DEFERRAL_MESSAGE
    assert "SETUP_ZOOM_SDK.md" in ZOOM_SDK_DEFERRAL_MESSAGE


def test_cleanup_is_noop():
    ZoomSDKAdapter().cleanup()  # 例外なく完了
