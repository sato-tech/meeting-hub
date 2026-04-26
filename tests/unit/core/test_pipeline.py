"""Pipeline オーケストレータのロジックテスト（Step 実装はモック）。"""
from __future__ import annotations

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
from core.pipeline import Pipeline
from core.steps.base import Step


class _FakeAdapter(InputAdapter):
    def __init__(self, path: Path):
        self._path = path

    def acquire(self, uri: str) -> Path:
        return self._path


@pytest.fixture(autouse=True)
def register_fake_step():
    calls = []

    @Step.register("preprocess", "_test_fake")
    class Fake(Step):
        def process(self, ctx: Context) -> Context:
            calls.append(self.name)
            ctx.audio_path = ctx.input_path
            return ctx

    @Step.register("format", "_test_fake")
    class FakeFmt(Step):
        def process(self, ctx: Context) -> Context:
            calls.append(self.name)
            out = ctx.work_dir / "dummy.md"
            out.write_text("ok", encoding="utf-8")
            ctx.outputs["md"] = out
            return ctx

    yield calls


def test_pipeline_runs_enabled_steps_in_order(tmp_path, register_fake_step):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_test_fake", params={}),
            StepConfig(step="transcribe", provider="faster_whisper_batch", enabled=False, params={}),
            StepConfig(step="format", provider="_test_fake", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination(path=str(tmp_path / "dst"))]),
    )
    adapter = _FakeAdapter(src)
    pipe = Pipeline(cassette, adapter)
    ctx = pipe.run(str(src), tmp_path / "out")

    assert register_fake_step == ["preprocess", "format"]  # transcribe は disabled でスキップ
    assert "md" in ctx.outputs


def test_pipeline_saves_checkpoints(tmp_path, register_fake_step):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_test_fake", params={}),
            StepConfig(step="format", provider="_test_fake", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination(path=str(tmp_path / "dst"))]),
    )
    pipe = Pipeline(cassette, _FakeAdapter(src))
    ctx = pipe.run(str(src), tmp_path / "out")

    cp_dir = ctx.work_dir / "checkpoints"
    assert (cp_dir / "preprocess.json").exists()
    assert (cp_dir / "format.json").exists()
