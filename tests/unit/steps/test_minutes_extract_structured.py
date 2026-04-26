"""minutes_extract の structured output 対応テスト（T4 / B5）。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.cassette_schema import (
    CassetteConfig,
    InputConfig,
    LocalDestination,
    LLMConfig,
    OutputConfig,
    StepConfig,
)
from core.context import Context
from core.steps.minutes_extract import ClaudeMinutesExtractStep


def _make_ctx(tmp_path):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("system prompt", encoding="utf-8")
    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="minutes_extract", provider="claude", params={"prompt": str(prompt_file)})],
        llm=LLMConfig(provider="claude", model="claude-haiku-4-5"),
        output=OutputConfig(destinations=[LocalDestination()]),
    )
    ctx = Context(
        input_path=tmp_path / "in.mp4",
        cassette=cassette,
        cleaned_text="本日は商談の件で…",
    )
    return cassette, ctx, prompt_file


def test_structured_output_uses_complete_json_when_enabled(tmp_path, monkeypatch):
    _, ctx, prompt_file = _make_ctx(tmp_path)
    step = ClaudeMinutesExtractStep(
        provider="claude",
        params={"prompt": str(prompt_file), "use_structured_output": True},
    )

    fake_client = MagicMock()
    fake_client.complete_json.return_value = {"meeting_title": "MTG", "summary_3lines": "A\nB\nC"}
    fake_client.complete.side_effect = AssertionError("complete() should not be called when structured works")
    fake_client.usage.input_tokens = 50
    fake_client.usage.output_tokens = 20
    monkeypatch.setattr(step, "_get_client", lambda ctx: fake_client)

    step.process(ctx)

    assert ctx.minutes == {"meeting_title": "MTG", "summary_3lines": "A\nB\nC"}
    assert ctx.meta["minutes_extract"]["mode"] == "structured"
    fake_client.complete_json.assert_called_once()


def test_structured_output_falls_back_to_text_on_failure(tmp_path, monkeypatch):
    _, ctx, prompt_file = _make_ctx(tmp_path)
    step = ClaudeMinutesExtractStep(
        provider="claude",
        params={"prompt": str(prompt_file), "use_structured_output": True},
    )

    fake_client = MagicMock()
    fake_client.complete_json.side_effect = RuntimeError("tool_use failed")
    fake_client.complete.return_value = '{"title": "fallback"}'
    fake_client.usage.input_tokens = 10
    fake_client.usage.output_tokens = 5
    monkeypatch.setattr(step, "_get_client", lambda ctx: fake_client)

    step.process(ctx)

    assert ctx.minutes == {"title": "fallback"}
    assert ctx.meta["minutes_extract"]["mode"] == "text"
    assert any("structured_fallback" in w for w in ctx.meta["warnings"])
    fake_client.complete.assert_called_once()


def test_default_mode_is_text(tmp_path, monkeypatch):
    _, ctx, prompt_file = _make_ctx(tmp_path)
    step = ClaudeMinutesExtractStep(provider="claude", params={"prompt": str(prompt_file)})

    fake_client = MagicMock()
    fake_client.complete.return_value = '{"a": 1}'
    fake_client.usage.input_tokens = 10
    fake_client.usage.output_tokens = 5
    monkeypatch.setattr(step, "_get_client", lambda ctx: fake_client)

    step.process(ctx)
    assert ctx.meta["minutes_extract"]["mode"] == "text"
    # complete_json は呼ばれない
    fake_client.complete_json.assert_not_called()
