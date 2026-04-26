"""RunService の動作テスト（Pipeline はフェイク Step で）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.history import JobHistory
from core.steps.base import Step
from web.run_service import RunService


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """フェイクの preprocess / format Step を登録。"""

    @Step.register("preprocess", "_run_service_fake")
    class P(Step):
        def process(self, ctx: Context) -> Context:
            ctx.audio_path = ctx.input_path
            return ctx

    @Step.register("format", "_run_service_fake")
    class F(Step):
        def process(self, ctx: Context) -> Context:
            out = ctx.work_dir / "dummy.md"
            out.write_text("done", encoding="utf-8")
            ctx.outputs["md"] = out
            return ctx

    return None


def test_start_job_records_history(tmp_path, fake_pipeline, monkeypatch):
    # 最小カセットを作ってロードできるようにする
    cassettes_dir = tmp_path / "cassettes"
    cassettes_dir.mkdir()
    (cassettes_dir / "min.yaml").write_text(
        """
name: min
mode: cloud_batch
input:
  type: file
  storage: local
pipeline:
  - step: preprocess
    provider: _run_service_fake
    params: {}
  - step: format
    provider: _run_service_fake
    params: {}
output:
  formats: [md]
  destinations:
    - type: local
      path: ./out
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.cassette._CASSETTE_ROOT", cassettes_dir)

    history = JobHistory(db_path=tmp_path / "h.db")
    svc = RunService(history, tmp_path / "out")

    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")

    job_id = svc.start_job(
        user_id="alice",
        cassette_name="min",
        input_path=src,
        run_in_thread=False,
    )
    rec = history.get(job_id)
    assert rec is not None
    assert rec.status == "completed"
    assert "dummy.md" in rec.meta["outputs"]["md"]


def test_start_job_records_failure(tmp_path, monkeypatch):
    """Step が例外を投げたとき failed で記録されるか。"""

    @Step.register("preprocess", "_run_service_fail")
    class F(Step):
        def process(self, ctx):
            raise RuntimeError("boom")

    cassettes_dir = tmp_path / "cassettes"
    cassettes_dir.mkdir()
    (cassettes_dir / "min.yaml").write_text(
        """
name: min
mode: cloud_batch
input:
  type: file
  storage: local
pipeline:
  - step: preprocess
    provider: _run_service_fail
    params: {}
output:
  destinations:
    - type: local
      path: ./out
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.cassette._CASSETTE_ROOT", cassettes_dir)

    history = JobHistory(db_path=tmp_path / "h.db")
    svc = RunService(history, tmp_path / "out")

    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")

    job_id = svc.start_job(user_id="u", cassette_name="min", input_path=src, run_in_thread=False)
    rec = history.get(job_id)
    assert rec.status == "failed"
    assert "boom" in rec.meta["error"]
