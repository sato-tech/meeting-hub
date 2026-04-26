"""LiveAudioAdapter — マイク + システム音声の 2ch キャプチャ。

Phase 2 スコープ:
  - macOS: BlackHole 2ch + Multi-Output Device を使った 2ch 録音
  - Windows: VB-Cable を使った 2ch 録音
  - いずれも **録音済み WAV のパスを返す**（擬似ストリーム、真ストリームは Phase 4）

設計:
  - `acquire(uri)` の uri は以下の形式:
    - `live://duration=60`             — 60 秒録音
    - `live://until-silence=5`         — 5 秒連続無音で停止（Phase 3 以降で実装予定）
    - `live://`（省略）                 — 既定 60 秒
  - 2ch mix モード:
    - `separate`: 左=self, 右=other。話者分離は diarize provider=channel_based で割当
    - `mono_merge`: 単ch 合成（pyannote で話者分離するとき用）
    - `diarize_ready`: 2chのまま維持（pyannote に渡す前提）
"""
from __future__ import annotations

import logging
import platform
import re
import tempfile
from pathlib import Path

from core.adapters.base import InputAdapter

logger = logging.getLogger(__name__)


_DEFAULT_SAMPLE_RATE = 48000
_DEFAULT_DURATION_SEC = 60.0
_DEFAULT_CHANNELS = 2


def detect_os() -> str:
    """macOS/windows/linux/unknown を返す。"""
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s.startswith("win"):
        return "windows"
    if s == "linux":
        return "linux"
    return "unknown"


def parse_live_uri(uri: str) -> dict:
    """`live://duration=60&channels=2` 形式をパース。"""
    out = {"duration": _DEFAULT_DURATION_SEC}
    if not uri or uri in ("live://", "live"):
        return out
    if "://" in uri:
        _, qs = uri.split("://", 1)
    else:
        qs = uri
    for pair in qs.split("&"):
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "duration":
            try:
                out["duration"] = float(v)
            except ValueError:
                logger.warning("invalid duration: %s", v)
        elif k == "channels":
            try:
                out["channels"] = int(v)
            except ValueError:
                pass
    return out


class LiveAudioAdapter(InputAdapter):
    """2ch ライブ録音アダプタ（macOS BlackHole / Windows VB-Cable）。

    参照: `docs/SETUP_LIVE_AUDIO_MACOS.md` / `docs/SETUP_LIVE_AUDIO_WINDOWS.md`
    """

    supports_streaming = False  # Phase 2 は録音完了後にバッチ処理

    # デバイス名の部分一致候補（OS 別）
    _DEVICE_CANDIDATES = {
        "macos": ["BlackHole 2ch", "BlackHole 16ch", "Multi-Output Device"],
        "windows": ["CABLE Output", "VB-Audio Virtual Cable"],
        "linux": ["pulse"],  # PulseAudio module-loopback
    }

    def __init__(
        self,
        *,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        channels: int = _DEFAULT_CHANNELS,
        device: str | int | None = None,
        mix: str = "separate",
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device  # None = 自動検出
        self.mix = mix
        self._tmp_files: list[Path] = []

    def acquire(self, uri: str) -> Path:
        opts = parse_live_uri(uri)
        duration = float(opts.get("duration", _DEFAULT_DURATION_SEC))
        channels = int(opts.get("channels", self.channels))

        device = self.device if self.device is not None else self._auto_detect_device()
        logger.info(
            "[live_audio] starting: device=%r duration=%.1fs channels=%d sr=%d",
            device, duration, channels, self.sample_rate,
        )

        audio = self._record(duration=duration, channels=channels, device=device)
        wav_path = self._write_wav(audio, channels=channels)
        self._tmp_files.append(wav_path)
        logger.info("[live_audio] saved: %s (%.1fs)", wav_path, duration)
        return wav_path

    def cleanup(self) -> None:
        # 一時 WAV はパイプライン側で参照中のため消さない。
        # 必要な場合は外側でディスク掃除を行う。
        return None

    # ─── 内部 ────────────────────────────────

    def _auto_detect_device(self):
        """OS に応じて既知のデバイス名から 1 件選ぶ（見つからなければ None）。"""
        import sounddevice as sd

        os_name = detect_os()
        candidates = self._DEVICE_CANDIDATES.get(os_name, [])
        devices = sd.query_devices()
        for cand in candidates:
            for i, d in enumerate(devices):
                name = d.get("name", "")
                if cand.lower() in name.lower() and d.get("max_input_channels", 0) >= 2:
                    logger.info("[live_audio] detected device: #%d %s", i, name)
                    return i
        logger.warning(
            "[live_audio] no known virtual audio device found. "
            "Install BlackHole (macOS) or VB-Cable (Windows). Using default input."
        )
        return None

    def _record(self, *, duration: float, channels: int, device):
        import sounddevice as sd

        audio = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=channels,
            device=device,
            dtype="float32",
        )
        sd.wait()
        return audio

    def _write_wav(self, audio, channels: int) -> Path:
        import numpy as np
        import soundfile as sf

        data = audio
        if self.mix == "mono_merge" and channels > 1:
            data = np.mean(audio, axis=1, keepdims=False).astype("float32")
        # separate / diarize_ready はそのまま多ch保存

        fd, path_str = tempfile.mkstemp(prefix="mh_live_", suffix=".wav")
        import os
        os.close(fd)
        path = Path(path_str)
        sf.write(str(path), data, self.sample_rate, subtype="PCM_16")
        return path
