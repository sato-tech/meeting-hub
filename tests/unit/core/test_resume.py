"""Pipeline の resume 機能テスト（Step はフェイク）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.adapters.base import InputAdapter
from core.cassette_schema import (
    CassetteConfig,
    InputConfig,
    LocalDestination,
    OutputConfig,
    StepConfig,
)
from core.context import Context
from core.pipeline import Pipeline, _load_latest_checkpoint, _save_checkpoint
from core.steps.base import Step


class _FakeAdapter(InputAdapter):
    def __init__(self, path: Path):
        self._path = path

    def acquire(self, uri: str) -> Path:
        return self._path


@pytest.fixture
def register_counting_steps():
    """呼ばれた Step を追跡するフェイク Step を登録する。"""
    call_log: list[str] = []

    @Step.register("preprocess", "_resume_fake")
    class PreStep(Step):
        def process(self, ctx: Context) -> Context:
            call_log.append("preprocess")
            ctx.audio_path = ctx.input_path
            ctx.segments = [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": "A"}]
            return ctx

    @Step.register("transcribe", "_resume_fake")
    class TrStep(Step):
        def process(self, ctx: Context) -> Context:
            call_log.append("transcribe")
            ctx.segments.append({"start": 1.0, "end": 2.0, "text": "world", "speaker": "A"})
            return ctx

    @Step.register("format", "_resume_fake")
    class FmtStep(Step):
        def process(self, ctx: Context) -> Context:
            call_log.append("format")
            out = ctx.work_dir / "dummy.md"
            out.write_text("ok", encoding="utf-8")
            ctx.outputs["md"] = out
            return ctx

    return call_log


def _make_cassette() -> CassetteConfig:
    return CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_resume_fake", params={}),
            StepConfig(step="transcribe", provider="_resume_fake", params={}),
            StepConfig(step="format", provider="_resume_fake", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination(path="./dst")]),
    )


def test_first_run_saves_checkpoints(tmp_path, register_counting_steps):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = _make_cassette()
    pipe = Pipeline(cassette, _FakeAdapter(src))
    ctx = pipe.run(str(src), tmp_path / "out")
    assert register_counting_steps == ["preprocess", "transcribe", "format"]

    cp_dir = ctx.work_dir / "checkpoints"
    for s in ("preprocess", "transcribe", "format"):
        assert (cp_dir / f"{s}.json").exists()


def test_resume_skips_completed_steps(tmp_path, register_counting_steps):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = _make_cassette()

    # 1 回目: 普通に完走
    pipe1 = Pipeline(cassette, _FakeAdapter(src))
    ctx1 = pipe1.run(str(src), tmp_path / "out")
    first_run_id = ctx1.run_id
    register_counting_steps.clear()

    # 2 回目: resume（format だけ再実行される想定だが、全 step 完走済みなので何も走らない）
    pipe2 = Pipeline(cassette, _FakeAdapter(src))
    ctx2 = pipe2.run(str(src), tmp_path / "out", resume_run_id=first_run_id)
    # 最後に完走した format が skip_up_to になるため何も実行されない
    assert register_counting_steps == []
    assert ctx2.meta.get("resumed_from") == "format"


def test_resume_continues_from_mid_step(tmp_path, register_counting_steps):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = _make_cassette()

    # 擬似的に transcribe までしか完走してない状態を作る
    run_id = "20260423_000000_in"
    work_dir = (tmp_path / "out") / run_id
    work_dir.mkdir(parents=True)
    ctx = Context(
        input_path=src, cassette=cassette, work_dir=work_dir, run_id=run_id,
        audio_path=src,
        segments=[{"start": 0.0, "end": 1.0, "text": "x", "speaker": "A"}],
    )
    _save_checkpoint(ctx, "preprocess")
    _save_checkpoint(ctx, "transcribe")

    pipe = Pipeline(cassette, _FakeAdapter(src))
    register_counting_steps.clear()
    pipe.run(str(src), tmp_path / "out", resume_run_id=run_id)
    # format のみ実行される
    assert register_counting_steps == ["format"]


def test_load_latest_checkpoint(tmp_path):
    work_dir = tmp_path / "run"
    (work_dir / "checkpoints").mkdir(parents=True)
    (work_dir / "checkpoints" / "preprocess.json").write_text('{"step": "preprocess"}', encoding="utf-8")
    (work_dir / "checkpoints" / "transcribe.json").write_text('{"step": "transcribe"}', encoding="utf-8")

    last, payload = _load_latest_checkpoint(work_dir, ["preprocess", "transcribe", "format"])
    assert last == "transcribe"
    assert payload["step"] == "transcribe"


def test_load_latest_checkpoint_empty(tmp_path):
    last, payload = _load_latest_checkpoint(tmp_path, ["preprocess", "format"])
    assert last is None
    assert payload == {}
