"""minutes_extract の JSON 抽出・リトライロジックテスト。"""
from __future__ import annotations

import json
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
from core.steps.minutes_extract import ClaudeMinutesExtractStep, _extract_json_block


def test_extract_json_block_codefenced() -> None:
    text = 'ここに説明\n```json\n{"a": 1, "b": "x"}\n```\n終わり'
    got = _extract_json_block(text)
    assert json.loads(got) == {"a": 1, "b": "x"}


def test_extract_json_block_plain() -> None:
    text = 'prelude... {"a": 1, "nested": {"b": 2}} postlude'
    got = _extract_json_block(text)
    assert json.loads(got) == {"a": 1, "nested": {"b": 2}}


def test_extract_json_block_raw() -> None:
    text = '{"a": 1}'
    got = _extract_json_block(text)
    assert json.loads(got) == {"a": 1}


def _make_cassette_and_ctx(tmp_path: Path, prompt_text: str):
    p_file = tmp_path / "p.md"
    p_file.write_text(prompt_text, encoding="utf-8")
    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[
            StepConfig(step="minutes_extract", provider="claude", params={"prompt": str(p_file)}),
        ],
        llm=LLMConfig(provider="claude", model="claude-haiku-4-5"),
        output=OutputConfig(destinations=[LocalDestination()]),
    )
    ctx = Context(
        input_path=tmp_path / "in.mp4",
        cassette=cassette,
        cleaned_text="本日は商談の件で…",
    )
    return cassette, ctx


def test_minutes_extract_success(monkeypatch, tmp_path: Path) -> None:
    cassette, ctx = _make_cassette_and_ctx(tmp_path, "system prompt")
    step = ClaudeMinutesExtractStep(provider="claude", params={"prompt": str(tmp_path / "p.md")})

    # ClaudeClient.complete を monkeypatch
    fake_client = MagicMock()
    fake_client.complete.return_value = '```json\n{"meeting_title": "MTG", "stage": "初回"}\n```'
    fake_client.usage.input_tokens = 100
    fake_client.usage.output_tokens = 50
    monkeypatch.setattr(step, "_get_client", lambda ctx: fake_client)

    step.process(ctx)
    assert ctx.minutes == {"meeting_title": "MTG", "stage": "初回"}
    assert ctx.meta["minutes_extract"]["tokens_in"] == 100


def test_minutes_extract_retries_on_bad_json(monkeypatch, tmp_path: Path) -> None:
    cassette, ctx = _make_cassette_and_ctx(tmp_path, "system prompt")
    step = ClaudeMinutesExtractStep(provider="claude", params={"prompt": str(tmp_path / "p.md")})

    fake_client = MagicMock()
    fake_client.complete.side_effect = [
        "not JSON at all, just explanation",  # 1st: invalid (no { })
        '{"title": "retry"}',                  # 2nd: valid
    ]
    fake_client.usage.input_tokens = 10
    fake_client.usage.output_tokens = 5
    monkeypatch.setattr(step, "_get_client", lambda ctx: fake_client)

    step.process(ctx)
    assert ctx.minutes == {"title": "retry"}
    assert "minutes_extract:retry_for_json" in ctx.meta["warnings"]
    assert fake_client.complete.call_count == 2


def test_minutes_extract_requires_prompt_param(tmp_path: Path) -> None:
    step = ClaudeMinutesExtractStep(provider="claude", params={})
    with pytest.raises(ValueError, match="`prompt`"):
        step._load_prompt()
