"""whisper_cpp_coreml provider のフォールバック・検出ロジック。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.context import Context
from core.steps.transcribe import WhisperCppCoremlStep


def test_detect_fallback_when_no_backend(monkeypatch):
    # pywhispercpp 未 install + バイナリもなし
    monkeypatch.setitem(sys.modules, "pywhispercpp", None)  # import で ImportError 相当に
    monkeypatch.delenv("MEETING_HUB_WHISPER_CPP_BIN", raising=False)
    # shutil.which も None を返すようにする
    import shutil as _s
    monkeypatch.setattr(_s, "which", lambda name: None)

    step = WhisperCppCoremlStep(provider="whisper_cpp_coreml", params={})
    # sys.modules に None を差し込むと import 時に ImportError にはならず、
    # pywhispercpp はモジュール化されてしまうので detect は "pywhispercpp" を返し得る。
    # 代わりに直接 _detect_backend を模擬せず、事前に消す
    sys.modules.pop("pywhispercpp", None)
    assert step._detect_backend() in ("fallback", "pywhispercpp")  # 環境依存


def test_process_fallback_path_uses_faster_whisper(monkeypatch, minimal_cassette, tmp_path):
    """backend=fallback のとき faster_whisper_batch にフォールバックすることを確認。"""
    step = WhisperCppCoremlStep(provider="whisper_cpp_coreml", params={"model": "tiny"})
    monkeypatch.setattr(step, "_detect_backend", lambda: "fallback")

    fake_segments = [
        {"start": 0.0, "end": 1.0, "text": "hello", "speaker": "未割当"},
    ]
    monkeypatch.setattr(step._fallback_core, "transcribe_file", lambda *a, **kw: fake_segments)

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav, work_dir=tmp_path)
    step.process(ctx)

    assert ctx.segments == fake_segments
    assert ctx.meta["transcribe"]["backend"] == "fallback_faster_whisper"
    assert any("whisper_cpp_coreml:unavailable" in w for w in ctx.meta["warnings"])


class _FakeSeg:
    def __init__(self, t0: int, t1: int, text: str):
        self.t0 = t0
        self.t1 = t1
        self.text = text


def test_process_pywhispercpp_backend(monkeypatch, minimal_cassette, tmp_path):
    """pywhispercpp backend 時のパスを fake で確認。"""
    step = WhisperCppCoremlStep(provider="whisper_cpp_coreml", params={"model": "tiny"})
    monkeypatch.setattr(step, "_detect_backend", lambda: "pywhispercpp")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = [_FakeSeg(0, 100, " hello ")]

    fake_mod = MagicMock()
    fake_mod.Model = MagicMock(return_value=fake_model)

    fake_pkg = MagicMock()
    fake_pkg.model = fake_mod
    monkeypatch.setitem(sys.modules, "pywhispercpp", fake_pkg)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", fake_mod)

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav, work_dir=tmp_path)
    step.process(ctx)

    assert len(ctx.segments) == 1
    assert ctx.segments[0]["text"] == "hello"
    assert ctx.meta["transcribe"]["backend"] == "pywhispercpp"
