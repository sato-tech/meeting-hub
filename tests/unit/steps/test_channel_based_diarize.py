"""channel_based diarize のテスト。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from core.cassette_schema import (
    CassetteConfig,
    InputConfig,
    LocalDestination,
    OutputConfig,
    StepConfig,
)
from core.context import Context
from core.steps.diarize import ChannelBasedDiarizeStep


def _write_2ch_wav(path: Path, sr: int = 16000) -> None:
    """2ch 合成音: 0-1s は Ch0 のみ（self）、1-2s は Ch1 のみ（other）。"""
    t = np.linspace(0, 2.0, 2 * sr, endpoint=False)
    ch0 = np.zeros_like(t)
    ch1 = np.zeros_like(t)
    ch0[:sr] = 0.5 * np.sin(2 * np.pi * 440 * t[:sr])  # self の 1秒
    ch1[sr:] = 0.5 * np.sin(2 * np.pi * 880 * t[sr:])  # other の 1秒
    stereo = np.stack([ch0, ch1], axis=1).astype(np.float32)
    sf.write(str(path), stereo, sr)


def _minimal_cassette() -> CassetteConfig:
    return CassetteConfig(
        name="test",
        mode="local_llm",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="diarize", provider="channel_based", params={})],
        output=OutputConfig(destinations=[LocalDestination()]),
    )


def test_channel_based_assigns_per_channel(tmp_path):
    wav = tmp_path / "stereo.wav"
    _write_2ch_wav(wav)

    cassette = _minimal_cassette()
    ctx = Context(input_path=wav, cassette=cassette, audio_path=wav)
    ctx.segments = [
        {"start": 0.1, "end": 0.9, "text": "self speaks", "speaker": "未割当"},
        {"start": 1.1, "end": 1.9, "text": "other speaks", "speaker": "未割当"},
    ]

    step = ChannelBasedDiarizeStep(
        provider="channel_based",
        params={"speaker_names": {"ch0": "マネージャ", "ch1": "メンバー"}},
    )
    step.process(ctx)
    assert ctx.segments[0]["speaker"] == "マネージャ"
    assert ctx.segments[1]["speaker"] == "メンバー"
    assert set(ctx.meta["diarize"]["speaker_time_distribution"].keys()) == {"マネージャ", "メンバー"}


def test_channel_based_falls_back_on_mono(tmp_path):
    wav = tmp_path / "mono.wav"
    sr = 16000
    data = (0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 1.0, sr))).astype(np.float32)
    sf.write(str(wav), data, sr)

    cassette = _minimal_cassette()
    ctx = Context(input_path=wav, cassette=cassette, audio_path=wav)
    ctx.segments = [{"start": 0.0, "end": 0.5, "text": "x", "speaker": "未割当"}]
    step = ChannelBasedDiarizeStep(provider="channel_based", params={})
    step.process(ctx)
    # mono の場合は UNKNOWN フォールバック
    assert ctx.segments[0]["speaker"] in ("UNKNOWN", "未割当")
