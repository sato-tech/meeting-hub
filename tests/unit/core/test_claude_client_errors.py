"""ClaudeClient の失敗系テスト（T3 / D）。"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from core.llm_client import ClaudeClient


def test_complete_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # anthropic モジュールの import を模擬
    fake_module = MagicMock()
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    client = ClaudeClient()
    with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
        client.complete("sys", "user")


def test_complete_retries_on_rate_limit_then_gives_up(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    class FakeRateLimitError(Exception):
        pass

    fake_module = MagicMock()
    fake_module.RateLimitError = FakeRateLimitError
    fake_inst = MagicMock()
    fake_inst.messages.create.side_effect = FakeRateLimitError("rate limited")
    fake_module.Anthropic = MagicMock(return_value=fake_inst)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    # sleep を短縮
    import core.llm_client as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    client = ClaudeClient(max_retries=2, base_backoff=1.0)
    with pytest.raises(RuntimeError, match="failed after 2 retries"):
        client.complete("sys", "user")
    # 2 回呼ばれる
    assert fake_inst.messages.create.call_count == 2


def test_extract_text_handles_missing_content():
    resp = MagicMock()
    resp.content = None
    assert ClaudeClient._extract_text(resp) == ""


def test_extract_text_joins_multiple_blocks():
    block1 = MagicMock()
    block1.text = "hello "
    block2 = MagicMock()
    block2.text = "world"
    resp = MagicMock()
    resp.content = [block1, block2]
    assert ClaudeClient._extract_text(resp) == "hello world"
