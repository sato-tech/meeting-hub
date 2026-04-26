"""StreamingPipeline の統合動作テスト（Step はフェイク）。"""
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
from core.steps.base import Step
from core.streaming.pipeline import StreamingJob, StreamingPipeline


class _FakeAdapter(InputAdapter):
    def __init__(self, path: Path):
        self._path = path

    def acquire(self, uri: str) -> Path:
        return self._path


@pytest.fixture
def streaming_fakes(tmp_path):
    """partial 通知をテストするためのフェイク transcribe + ダミー format。"""
    captured_partials: list[list[dict]] = []

    @Step.register("preprocess", "_stream_test")
    class P(Step):
        def process(self, ctx: Context) -> Context:
            ctx.audio_path = ctx.input_path
            return ctx

    @Step.register("transcribe", "_stream_test")
    class T(Step):
        def process(self, ctx: Context) -> Context:
            # 2 チャンク分の partial を擬似通知
            partial_cb = ctx.meta.get("transcribe_on_partial")
            ctx.segments = [
                {"start": 0.0, "end": 2.0, "text": "hello", "speaker": "A"},
                {"start": 20.0, "end": 22.0, "text": "world", "speaker": "A"},
            ]
            if partial_cb:
                partial_cb([ctx.segments[0]])
                partial_cb([ctx.segments[1]])
            return ctx

    @Step.register("format", "_stream_test")
    class F(Step):
        def process(self, ctx: Context) -> Context:
            out = ctx.work_dir / "x.md"
            out.write_text("done", encoding="utf-8")
            ctx.outputs["md"] = out
            return ctx

    return captured_partials


def _make_cassette() -> CassetteConfig:
    return CassetteConfig(
        name="test_stream",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_stream_test", params={}),
            StepConfig(step="transcribe", provider="_stream_test", params={}),
            StepConfig(step="format", provider="_stream_test", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination(path="./d")]),
    )


def test_streaming_run_async_emits_partials_and_completes(tmp_path, streaming_fakes):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cassette = _make_cassette()

    received_partials: list[list[dict]] = []

    def on_partial(segs):
        received_partials.append(segs)

    pipe = StreamingPipeline(cassette, _FakeAdapter(src), on_partial=on_partial)
    job = pipe.run_async(str(src), tmp_path / "out")

    events = list(job.partial_events(timeout=5.0))
    kinds = [e[0] for e in events]
    assert kinds.count("partial") == 2
    assert kinds[-1] == "complete"

    ctx = job.wait(timeout=5.0)
    assert len(ctx.segments) == 2
    assert "md" in ctx.outputs
    assert len(received_partials) == 2


def test_streaming_job_propagates_errors(tmp_path):
    @Step.register("preprocess", "_stream_fail")
    class P(Step):
        def process(self, ctx: Context) -> Context:
            raise RuntimeError("boom")

    cassette = CassetteConfig(
        name="t",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[StepConfig(step="preprocess", provider="_stream_fail", params={})],
        output=OutputConfig(destinations=[LocalDestination()]),
    )
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    pipe = StreamingPipeline(cassette, _FakeAdapter(src))
    job = pipe.run_async(str(src), tmp_path / "out")
    events = list(job.partial_events(timeout=5.0))
    assert events[-1][0] == "error"
    with pytest.raises(RuntimeError, match="boom"):
        job.wait(timeout=5.0)
