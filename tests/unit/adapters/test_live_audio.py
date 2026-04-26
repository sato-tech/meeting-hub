"""LiveAudioAdapter のユニットテスト（sounddevice は mock）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.adapters.live_audio import LiveAudioAdapter, detect_os, parse_live_uri


def test_parse_live_uri_defaults() -> None:
    assert parse_live_uri("") == {"duration": 60.0}
    assert parse_live_uri("live://") == {"duration": 60.0}


def test_parse_live_uri_duration() -> None:
    assert parse_live_uri("live://duration=120") == {"duration": 120.0}


def test_parse_live_uri_multiple_fields() -> None:
    out = parse_live_uri("live://duration=30&channels=2")
    assert out["duration"] == 30.0
    assert out["channels"] == 2


def test_parse_live_uri_invalid_duration() -> None:
    out = parse_live_uri("live://duration=abc")
    # 不正値は無視され既定値を維持
    assert out["duration"] == 60.0


def test_detect_os_returns_known_label() -> None:
    assert detect_os() in ("macos", "windows", "linux", "unknown")


def test_acquire_records_and_returns_path(mocker, tmp_path: Path) -> None:
    import numpy as np

    # sounddevice を丸ごと fake
    fake_sd = mocker.MagicMock()
    fake_sd.query_devices.return_value = [
        {"name": "BlackHole 2ch", "max_input_channels": 2},
        {"name": "Default Mic", "max_input_channels": 1},
    ]
    fake_sd.rec.return_value = np.zeros((48000, 2), dtype="float32")
    fake_sd.wait.return_value = None
    mocker.patch.dict("sys.modules", {"sounddevice": fake_sd})

    adapter = LiveAudioAdapter(sample_rate=48000, channels=2)
    out = adapter.acquire("live://duration=1.0")

    assert out.exists()
    assert out.suffix == ".wav"
    fake_sd.rec.assert_called_once()
    kwargs = fake_sd.rec.call_args.kwargs
    assert kwargs["samplerate"] == 48000
    assert kwargs["channels"] == 2


def test_acquire_auto_detects_blackhole_on_macos(mocker) -> None:
    import numpy as np

    fake_sd = mocker.MagicMock()
    fake_sd.query_devices.return_value = [
        {"name": "MacBook Mic", "max_input_channels": 1},
        {"name": "BlackHole 2ch", "max_input_channels": 2},
        {"name": "Speakers", "max_input_channels": 0},
    ]
    fake_sd.rec.return_value = np.zeros((48000, 2), dtype="float32")
    mocker.patch.dict("sys.modules", {"sounddevice": fake_sd})
    mocker.patch("core.adapters.live_audio.detect_os", return_value="macos")

    adapter = LiveAudioAdapter(sample_rate=48000, channels=2)
    adapter.acquire("live://duration=0.1")

    # device=1 (BlackHole) が使われる
    kwargs = fake_sd.rec.call_args.kwargs
    assert kwargs["device"] == 1
