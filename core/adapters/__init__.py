"""InputAdapter 実装群。"""
from core.adapters.file import FileAdapter  # noqa: F401
from core.adapters.live_audio import LiveAudioAdapter  # noqa: F401
from core.adapters.zoom_sdk import ZoomSDKAdapter  # noqa: F401

__all__ = ["FileAdapter", "LiveAudioAdapter", "ZoomSDKAdapter"]
