"""ClaudeClient.complete_json() のテスト（T4）。"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from core.llm_client import ClaudeClient


def test_complete_json_returns_tool_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    fake_module = MagicMock()
    fake_inst = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "record_minutes"
    tool_block.input = {"meeting_title": "MTG", "stage": "初回"}
    resp = MagicMock()
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    fake_inst.messages.create.return_value = resp
    fake_module.Anthropic = MagicMock(return_value=fake_inst)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    client = ClaudeClient()
    result = client.complete_json("system", "user")
    assert result == {"meeting_title": "MTG", "stage": "初回"}
    # tool_use kwargs が正しく組まれている
    call_kwargs = fake_inst.messages.create.call_args.kwargs
    assert "tools" in call_kwargs
    assert call_kwargs["tools"][0]["name"] == "record_minutes"
    assert call_kwargs["tool_choice"]["type"] == "tool"


def test_complete_json_raises_when_no_tool_use_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    fake_module = MagicMock()
    fake_inst = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    resp = MagicMock()
    resp.content = [text_block]
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    fake_inst.messages.create.return_value = resp
    fake_module.Anthropic = MagicMock(return_value=fake_inst)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    client = ClaudeClient()
    with pytest.raises(Exception, match="tool_use block not found"):
        client.complete_json("system", "user")


def test_complete_json_uses_custom_schema(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    fake_module = MagicMock()
    fake_inst = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "record_minutes"
    tool_block.input = {"title": "x"}
    resp = MagicMock()
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=1, output_tokens=1)
    fake_inst.messages.create.return_value = resp
    fake_module.Anthropic = MagicMock(return_value=fake_inst)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    custom_schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }

    client = ClaudeClient()
    result = client.complete_json("s", "u", input_schema=custom_schema)
    assert result == {"title": "x"}
    call_kwargs = fake_inst.messages.create.call_args.kwargs
    assert call_kwargs["tools"][0]["input_schema"] == custom_schema
