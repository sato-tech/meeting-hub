"""Slack destination のテスト（slack_sdk は mock）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.cassette_schema import SlackDestination
from core.context import Context
from core.destinations import SlackDestinationImpl


@pytest.fixture
def fake_slack(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    fake_module = MagicMock()
    fake_client = MagicMock()
    fake_client.chat_postMessage.return_value = {"ts": "1234.5678"}
    fake_client.files_upload_v2.return_value = {"ts": "1234.5678"}
    fake_module.WebClient = MagicMock(return_value=fake_client)
    fake_module.errors = MagicMock()
    fake_module.errors.SlackApiError = type("SlackApiError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "slack_sdk", fake_module)
    monkeypatch.setitem(sys.modules, "slack_sdk.errors", fake_module.errors)
    return fake_client


def test_summary_only_posts_message(fake_slack, minimal_cassette, tmp_path):
    impl = SlackDestinationImpl(SlackDestination(channel="#sales", post_format="summary_only"))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "Deal X", "date": "2026-04-23", "summary_3lines": "L1\nL2\nL3"}
    impl.send(ctx)
    fake_slack.chat_postMessage.assert_called_once()
    text = fake_slack.chat_postMessage.call_args.kwargs["text"]
    assert "Deal X" in text
    assert "L1" in text


def test_full_minutes_uploads_file(fake_slack, minimal_cassette, tmp_path):
    md = tmp_path / "x.md"
    md.write_text("# title\n\ncontent", encoding="utf-8")
    impl = SlackDestinationImpl(SlackDestination(channel="#sales", post_format="full_minutes"))
    ctx = Context(input_path=tmp_path / "src", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "Weekly"}
    ctx.outputs["md"] = md
    impl.send(ctx)
    fake_slack.files_upload_v2.assert_called_once()


def test_no_token_raises(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    impl = SlackDestinationImpl(SlackDestination(channel="#x", post_format="summary_only"))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    with pytest.raises(EnvironmentError):
        impl.send(ctx)
