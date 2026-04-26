"""MEETING_HUB_FORCE_MODAL env による runtime 強制のテスト。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.cassette import _apply_force_modal, _force_modal_enabled, load_cassette
from core.context import Context
from core.runtime import ModalRuntime
from core.steps.base import Step


# ─── _force_modal_enabled の env 解釈 ──
@pytest.mark.parametrize("env_value,expected", [
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("1", True),
    ("yes", True),
    ("YES", True),
    ("on", True),
    ("false", False),
    ("0", False),
    ("no", False),
    ("", False),
    ("random_string", False),
])
def test_force_modal_enabled_env_parsing(monkeypatch, env_value, expected):
    monkeypatch.setenv("MEETING_HUB_FORCE_MODAL", env_value)
    assert _force_modal_enabled() is expected


def test_force_modal_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("MEETING_HUB_FORCE_MODAL", raising=False)
    assert _force_modal_enabled() is False


# ─── _apply_force_modal が transcribe/diarize の runtime を上書き ──
def test_apply_force_modal_overrides_transcribe_and_diarize():
    data = {
        "pipeline": [
            {"step": "preprocess", "runtime": "local"},
            {"step": "transcribe", "runtime": "local"},
            {"step": "diarize", "runtime": "local"},
            {"step": "term_correct", "runtime": "local"},
            {"step": "llm_cleanup", "runtime": "local"},
            {"step": "minutes_extract", "runtime": "local"},
            {"step": "format", "runtime": "local"},
        ]
    }
    _apply_force_modal(data)
    runtimes = {s["step"]: s["runtime"] for s in data["pipeline"]}
    assert runtimes["transcribe"] == "modal"
    assert runtimes["diarize"] == "modal"
    # 他はそのまま
    assert runtimes["preprocess"] == "local"
    assert runtimes["llm_cleanup"] == "local"
    assert runtimes["format"] == "local"


def test_apply_force_modal_with_no_pipeline():
    data = {}
    _apply_force_modal(data)
    assert data == {}


def test_apply_force_modal_adds_runtime_when_missing():
    """元々 runtime キーが無い step にも追加される。"""
    data = {"pipeline": [{"step": "transcribe"}]}
    _apply_force_modal(data)
    assert data["pipeline"][0]["runtime"] == "modal"


# ─── load_cassette との統合 ──
def test_load_cassette_with_force_modal_env_overrides_runtime(monkeypatch):
    monkeypatch.setenv("MEETING_HUB_FORCE_MODAL", "true")
    c = load_cassette("sales_meeting")
    transcribe = c.get_step("transcribe")
    diarize = c.get_step("diarize")
    assert transcribe.runtime == "modal"
    assert diarize.runtime == "modal"


def test_load_cassette_without_force_modal_keeps_original(monkeypatch):
    monkeypatch.delenv("MEETING_HUB_FORCE_MODAL", raising=False)
    c = load_cassette("sales_meeting")
    # sales_meeting.yaml は transcribe.runtime=local が既定
    transcribe = c.get_step("transcribe")
    assert transcribe.runtime == "local"


def test_load_cassette_force_modal_skipped_for_live_audio(monkeypatch):
    """live + force_modal の組合せでは Modal 強制をスキップ（Phase 0 プライバシー要件）。

    ライブ音声は Modal に送らない設計（cassette_schema.validate_mode_consistency で強制）。
    HF Spaces にデプロイ時はマイク入力がなく live_audio が実用的に使えないため、
    force_modal は無効化される（schema validation 違反を防ぐ）。
    """
    monkeypatch.setenv("MEETING_HUB_FORCE_MODAL", "true")
    c = load_cassette("sales_meeting", live=True)
    transcribe = c.get_step("transcribe")
    # ライブプロファイルは適用されているが、runtime は local のまま
    assert transcribe.provider == "faster_whisper_chunked"
    assert transcribe.runtime == "local"


def test_apply_force_modal_skips_live_audio_input():
    """input.type=live_audio の場合、Modal 強制を行わない。"""
    data = {
        "input": {"type": "live_audio"},
        "pipeline": [
            {"step": "transcribe", "runtime": "local"},
            {"step": "diarize", "runtime": "local"},
        ],
    }
    _apply_force_modal(data)
    # 変更されない
    assert data["pipeline"][0]["runtime"] == "local"
    assert data["pipeline"][1]["runtime"] == "local"


# ─── ModalRuntime の fail-loud 挙動 ──
def test_modal_runtime_fails_loud_when_forced_and_remote_unavailable(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.setenv("MEETING_HUB_FORCE_MODAL", "true")

    class _FakeStep(Step):
        def process(self, ctx: Context) -> Context:
            raise AssertionError("local fallback should not be called when forced")

    step = _FakeStep(provider="faster_whisper_batch", params={})
    step.name = "transcribe"  # type: ignore

    runtime = ModalRuntime()
    monkeypatch.setattr(runtime, "_get_remote_fn", lambda step_name: None)

    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    with pytest.raises(RuntimeError, match="MEETING_HUB_FORCE_MODAL is set"):
        runtime.execute(step, ctx)


def test_modal_runtime_fallbacks_when_not_forced(monkeypatch, minimal_cassette, tmp_path):
    """forced でなければ従来通りローカル fallback が動く。"""
    monkeypatch.delenv("MEETING_HUB_FORCE_MODAL", raising=False)

    class _FakeStep(Step):
        def process(self, ctx: Context) -> Context:
            ctx.meta["fallback_called"] = True
            return ctx

    step = _FakeStep(provider="faster_whisper_batch", params={})
    step.name = "transcribe"  # type: ignore

    runtime = ModalRuntime()
    monkeypatch.setattr(runtime, "_get_remote_fn", lambda step_name: None)

    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    runtime.execute(step, ctx)
    assert ctx.meta.get("fallback_called") is True
    assert any("modal:unavailable" in w for w in ctx.meta.get("warnings", []))


def test_modal_runtime_fails_loud_on_remote_call_error_when_forced(monkeypatch, minimal_cassette, tmp_path):
    """remote_fn.remote() が例外を投げた場合も fail-loud になる。"""
    monkeypatch.setenv("MEETING_HUB_FORCE_MODAL", "true")

    class _FakeStep(Step):
        def process(self, ctx: Context) -> Context:
            raise AssertionError("local fallback should not be called when forced")

    step = _FakeStep(provider="faster_whisper_batch", params={})
    step.name = "transcribe"  # type: ignore

    fake_remote_fn = MagicMock()
    fake_remote_fn.remote.side_effect = ConnectionError("modal network failure")

    runtime = ModalRuntime()
    monkeypatch.setattr(runtime, "_get_remote_fn", lambda step_name: fake_remote_fn)

    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette, audio_path=tmp_path / "x")
    with pytest.raises(RuntimeError, match="MEETING_HUB_FORCE_MODAL is set"):
        runtime.execute(step, ctx)
