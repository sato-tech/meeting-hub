"""format Step の描画関数テスト。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cassette_schema import (
    CassetteConfig,
    InputConfig,
    LocalDestination,
    OutputConfig,
    StepConfig,
)
from core.context import Context
from core.steps.format import FormatStep, render_srt, render_txt


def _seg(start: float, end: float, text: str, speaker: str = "A") -> dict:
    return {"start": start, "end": end, "text": text, "speaker": speaker}


def test_render_txt_shape() -> None:
    out = render_txt([_seg(0.0, 1.0, "hello", "A")])
    assert "[0.0s] A:" in out
    assert "hello" in out


def test_render_srt_time_format() -> None:
    out = render_srt([_seg(0.0, 3.5, "x", "A")])
    assert "00:00:00,000 --> 00:00:03,500" in out
    assert "1\n" in out


def test_format_step_writes_txt_json_srt(tmp_path: Path) -> None:
    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="format", params={})],
        output=OutputConfig(formats=["txt", "json", "srt"], destinations=[LocalDestination()]),
    )
    ctx = Context(
        input_path=Path("/tmp/demo.mp4"),
        cassette=cassette,
        work_dir=tmp_path,
        segments=[_seg(0.0, 1.5, "hello")],
    )
    FormatStep(provider="default", params={}).process(ctx)

    assert ctx.outputs["txt"].exists()
    assert ctx.outputs["json"].exists()
    assert ctx.outputs["srt"].exists()
    data = json.loads(ctx.outputs["json"].read_text(encoding="utf-8"))
    assert data[0]["text"] == "hello"


def test_format_step_renders_md_with_jinja(tmp_path: Path) -> None:
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    tpl = tpl_dir / "basic.md.j2"
    tpl.write_text("# {{ minutes.title }}\n\n{{ cleaned_text }}", encoding="utf-8")

    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="format", params={})],
        output=OutputConfig(
            formats=["md"],
            template=str(tpl),
            destinations=[LocalDestination()],
        ),
    )
    ctx = Context(
        input_path=Path("/tmp/demo.mp4"),
        cassette=cassette,
        work_dir=tmp_path,
        cleaned_text="本文です",
    )
    ctx.minutes = {"title": "テストMTG"}
    FormatStep(provider="default", params={}).process(ctx)

    md = ctx.outputs["md"].read_text(encoding="utf-8")
    assert "# テストMTG" in md
    assert "本文です" in md
