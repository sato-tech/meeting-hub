"""Notion destination のテスト（notion_client は mock）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.cassette_schema import NotionDestination
from core.context import Context
from core.destinations import (
    NotionDestinationImpl,
    _build_properties,
    _expand_env,
    _render_template,
)


def test_expand_env(monkeypatch):
    monkeypatch.setenv("NOTION_DB_SALES", "abc123")
    assert _expand_env("${NOTION_DB_SALES}") == "abc123"


def test_expand_env_missing(monkeypatch):
    monkeypatch.delenv("NOTION_DB_MISSING", raising=False)
    with pytest.raises(EnvironmentError):
        _expand_env("${NOTION_DB_MISSING}")


def test_render_template():
    out = _render_template("{{ meeting_title }} - {{ date }}", {"meeting_title": "MTG", "date": "2026-04-23"}, {})
    assert out == "MTG - 2026-04-23"


def test_build_properties_first_key_becomes_title():
    props = _build_properties(
        {"Title": "{{ meeting_title }}", "Date": "{{ date }}"},
        {"meeting_title": "Weekly", "date": "2026-04-23"},
        {},
    )
    assert "title" in props["Title"]
    assert props["Title"]["title"][0]["text"]["content"] == "Weekly"
    assert "date" in props["Date"]
    assert props["Date"]["date"]["start"] == "2026-04-23"


def test_send_without_token_raises(minimal_cassette, monkeypatch, tmp_path):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    impl = NotionDestinationImpl(NotionDestination(database_id="x", properties={"Title": "t"}))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    with pytest.raises(EnvironmentError):
        impl.send(ctx)


def test_send_creates_page(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DB_TEST", "db_abc")

    fake_client_class = MagicMock()
    fake_instance = MagicMock()
    fake_instance.pages.create.return_value = {"id": "page_123"}
    fake_client_class.return_value = fake_instance
    fake_module = MagicMock(Client=fake_client_class)
    monkeypatch.setitem(sys.modules, "notion_client", fake_module)

    impl = NotionDestinationImpl(NotionDestination(
        database_id="${NOTION_DB_TEST}",
        properties={"Title": "{{ meeting_title }}"},
    ))
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "1on1"}
    impl.send(ctx)

    fake_instance.pages.create.assert_called_once()
    kwargs = fake_instance.pages.create.call_args.kwargs
    assert kwargs["parent"] == {"database_id": "db_abc"}
    assert "Title" in kwargs["properties"]
    assert ctx.meta["destinations"]["notion"][0]["page_id"] == "page_123"
