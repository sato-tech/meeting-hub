"""WhisperX align 統合のテスト（T5 / A2）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.context import Context
from core.steps.diarize import PyannoteDiarizeStep


def _ctx(minimal_cassette, tmp_path: Path) -> Context:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav)
    ctx.segments = [
        {"start": 0.0, "end": 2.0, "text": "hello", "speaker": "未割当"},
        {"start": 2.0, "end": 4.0, "text": "world", "speaker": "未割当"},
    ]
    return ctx


def test_align_mode_whisperx_when_available(monkeypatch, minimal_cassette, tmp_path):
    """whisperx が使えるとき align_mode=whisperx_align になる。"""
    step = PyannoteDiarizeStep(provider="pyannote", params={})

    # pyannote pipeline を fake
    fake_diar = MagicMock()
    monkeypatch.setattr(step, "_load_pipeline", lambda: lambda audio, **kw: fake_diar)

    # whisperx fake module
    fake_wx = MagicMock()
    fake_wx.load_audio.return_value = b"fake_audio"
    fake_wx.load_align_model.return_value = (MagicMock(), MagicMock())
    fake_wx.align.return_value = {"segments": []}
    fake_wx.assign_word_speakers.return_value = {
        "segments": [
            {"speaker": "SPEAKER_00"},
            {"speaker": "SPEAKER_01"},
        ]
    }
    monkeypatch.setitem(sys.modules, "whisperx", fake_wx)

    ctx = _ctx(minimal_cassette, tmp_path)
    step.process(ctx)
    assert ctx.meta["diarize"]["align_mode"] == "whisperx_align"
    assert ctx.segments[0]["speaker"] == "SPEAKER_00"
    assert ctx.segments[1]["speaker"] == "SPEAKER_01"


def test_align_falls_back_to_coarse_on_whisperx_error(monkeypatch, minimal_cassette, tmp_path):
    """whisperx が ImportError / align 失敗などを投げたら粗い割当にフォールバック。"""
    step = PyannoteDiarizeStep(provider="pyannote", params={})

    # fake pyannote diarization が 2 トラックを返す
    class FakeTurn:
        def __init__(self, s, e):
            self.start = s
            self.end = e

    class FakeDiar:
        def itertracks(self, yield_label=False):
            yield FakeTurn(0.0, 2.0), "t0", "SPEAKER_00"
            yield FakeTurn(2.0, 4.0), "t1", "SPEAKER_01"

    monkeypatch.setattr(step, "_load_pipeline", lambda: lambda audio, **kw: FakeDiar())

    # whisperx が ImportError するように差し替え
    def raise_import(*a, **kw):
        raise ImportError("whisperx not installed")

    monkeypatch.setattr(step, "_apply_with_whisperx_align", raise_import)

    ctx = _ctx(minimal_cassette, tmp_path)
    step.process(ctx)

    assert ctx.meta["diarize"]["align_mode"] == "coarse"
    assert any("whisperx_fallback" in w for w in ctx.meta["warnings"])
    # coarse でも SPEAKER_* ラベルが割当済み
    assert ctx.segments[0]["speaker"] == "SPEAKER_00"
    assert ctx.segments[1]["speaker"] == "SPEAKER_01"


def test_use_whisperx_align_false_skips_align(monkeypatch, minimal_cassette, tmp_path):
    """params で use_whisperx_align=false なら coarse 直行。whisperx は呼ばれない。"""
    step = PyannoteDiarizeStep(
        provider="pyannote", params={"use_whisperx_align": False}
    )

    class FakeTurn:
        def __init__(self, s, e):
            self.start = s
            self.end = e

    class FakeDiar:
        def itertracks(self, yield_label=False):
            yield FakeTurn(0.0, 2.0), "t0", "SPEAKER_00"
            yield FakeTurn(2.0, 4.0), "t1", "SPEAKER_01"

    monkeypatch.setattr(step, "_load_pipeline", lambda: lambda audio, **kw: FakeDiar())
    mock_align = MagicMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr(step, "_apply_with_whisperx_align", mock_align)

    ctx = _ctx(minimal_cassette, tmp_path)
    step.process(ctx)

    assert ctx.meta["diarize"]["align_mode"] == "coarse"
    mock_align.assert_not_called()
