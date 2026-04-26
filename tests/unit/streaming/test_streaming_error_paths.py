"""StreamingJob の error path / adapter 異常系テスト（T3 / D）。"""
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
from core.streaming.pipeline import StreamingPipeline


class _RaisingAdapter(InputAdapter):
    """acquire で必ず例外を投げるアダプタ。"""
    def acquire(self, uri: str) -> Path:
        raise RuntimeError("adapter failure simulated")


class _OkAdapter(InputAdapter):
    def __init__(self, path: Path):
        self._path = path

    def acquire(self, uri: str) -> Path:
        return self._path


def _make_cassette() -> CassetteConfig:
    return CassetteConfig(
        name="t_err",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_stream_err_fake", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination()]),
    )


@pytest.fixture
def register_fake_steps():
    @Step.register("preprocess", "_stream_err_fake")
    class P(Step):
        def process(self, ctx: Context) -> Context:
            ctx.audio_path = ctx.input_path
            return ctx


def test_streaming_job_propagates_adapter_error(tmp_path, register_fake_steps):
    cassette = _make_cassette()
    pipe = StreamingPipeline(cassette, _RaisingAdapter())
    job = pipe.run_async("any_uri", tmp_path / "out")

    events = list(job.partial_events(timeout=5.0))
    kinds = [e[0] for e in events]
    assert "error" in kinds
    with pytest.raises(RuntimeError, match="adapter failure simulated"):
        job.wait(timeout=5.0)


def test_streaming_job_user_on_partial_exception_is_swallowed(tmp_path, register_fake_steps):
    """ユーザーの on_partial が例外を投げてもジョブは継続する。"""

    @Step.register("transcribe", "_stream_err_fake")
    class T(Step):
        def process(self, ctx: Context) -> Context:
            cb = ctx.meta.get("transcribe_on_partial")
            if cb:
                cb([{"start": 0.0, "end": 1.0, "text": "x", "speaker": "A"}])
            ctx.segments = [{"start": 0.0, "end": 1.0, "text": "x", "speaker": "A"}]
            return ctx

    @Step.register("format", "_stream_err_fake")
    class F(Step):
        def process(self, ctx: Context) -> Context:
            return ctx

    cassette = CassetteConfig(
        name="t_err2",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="_stream_err_fake", params={}),
            StepConfig(step="transcribe", provider="_stream_err_fake", params={}),
            StepConfig(step="format", provider="_stream_err_fake", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination()]),
    )

    def bad_partial(segs):
        raise ValueError("user handler crashed")

    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    pipe = StreamingPipeline(cassette, _OkAdapter(src), on_partial=bad_partial)
    job = pipe.run_async(str(src), tmp_path / "out")
    ctx = job.wait(timeout=5.0)
    # ジョブは完走する
    assert len(ctx.segments) == 1
