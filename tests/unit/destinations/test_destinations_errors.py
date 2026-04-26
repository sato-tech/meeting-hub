"""destinations のネットワーク異常系テスト（T3 / D）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.cassette_schema import NotionDestination, SlackDestination
from core.context import Context
from core.destinations import NotionDestinationImpl, SlackDestinationImpl


def test_notion_network_error_propagates(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.setenv("NOTION_API_KEY", "secret")

    fake_client = MagicMock()
    fake_client.pages.create.side_effect = ConnectionError("network down")
    fake_module = MagicMock(Client=MagicMock(return_value=fake_client))
    monkeypatch.setitem(sys.modules, "notion_client", fake_module)

    impl = NotionDestinationImpl(NotionDestination(database_id="abc", properties={"Title": "x"}))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "M"}
    with pytest.raises(ConnectionError, match="network down"):
        impl.send(ctx)


def test_slack_api_error_is_wrapped(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")

    class FakeSlackApiError(Exception):
        def __init__(self, resp):
            self.response = resp

    fake_mod = MagicMock()
    fake_client = MagicMock()
    fake_client.chat_postMessage.side_effect = FakeSlackApiError({"error": "channel_not_found"})
    fake_mod.WebClient = MagicMock(return_value=fake_client)
    fake_mod.errors = MagicMock(SlackApiError=FakeSlackApiError)
    monkeypatch.setitem(sys.modules, "slack_sdk", fake_mod)
    monkeypatch.setitem(sys.modules, "slack_sdk.errors", fake_mod.errors)

    impl = SlackDestinationImpl(SlackDestination(channel="#x", post_format="summary_only"))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "M"}

    with pytest.raises(RuntimeError, match="channel_not_found"):
        impl.send(ctx)


def test_destination_unknown_type_raises():
    from core.destinations import Destination

    class FakeCfg:
        type = "nonexistent_provider_xyz"

    with pytest.raises(ValueError, match="No Destination registered"):
        Destination.create(FakeCfg())
