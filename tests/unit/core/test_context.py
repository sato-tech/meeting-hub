"""Context dataclass のユニットテスト。"""
from __future__ import annotations

from pathlib import Path

from core.context import Context


def test_context_defaults(minimal_cassette) -> None:
    ctx = Context(input_path=Path("/tmp/foo.mp4"), cassette=minimal_cassette)
    assert ctx.segments == []
    assert ctx.audio_path is None
    assert ctx.cleaned_text is None
    assert ctx.minutes is None
    assert ctx.outputs == {}
    assert ctx.streaming is False
    assert ctx.meta == {}


def test_step_params_returns_params(minimal_cassette) -> None:
    ctx = Context(input_path=Path("/tmp/foo.mp4"), cassette=minimal_cassette)
    assert ctx.step_params("preprocess") == {"target_sr": 16000}
    assert ctx.step_params("transcribe") == {"model": "tiny"}


def test_step_params_unknown_step_returns_empty(minimal_cassette) -> None:
    ctx = Context(input_path=Path("/tmp/foo.mp4"), cassette=minimal_cassette)
    # StepName 外の値を文字列で入れても空 dict を返す（防御的）
    assert ctx.step_params("nonexistent") == {}  # type: ignore[arg-type]


def test_add_warning_and_timings(minimal_cassette) -> None:
    ctx = Context(input_path=Path("/tmp/foo.mp4"), cassette=minimal_cassette)
    ctx.add_warning("external notion skipped")
    ctx.record_timing("preprocess", 1.5)
    assert ctx.meta["warnings"] == ["external notion skipped"]
    assert ctx.meta["timings"] == {"preprocess": 1.5}
