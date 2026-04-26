"""Email destination のテスト（smtplib は mock）。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.cassette_schema import EmailDestination
from core.context import Context
from core.destinations import EmailDestinationImpl


def test_send_success(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.setenv("GMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "xxxx yyyy zzzz aaaa")

    md = tmp_path / "x.md"
    md.write_text("md body", encoding="utf-8")

    impl = EmailDestinationImpl(EmailDestination(
        to=["a@example.com"],
        cc=["b@example.com"],
        subject="【議事録】{{ meeting_title }}",
    ))
    ctx = Context(input_path=tmp_path / "src", cassette=minimal_cassette)
    ctx.minutes = {"meeting_title": "Weekly", "date": "2026-04-23", "summary_3lines": "x"}
    ctx.cleaned_text = "本文..."
    ctx.outputs["md"] = md

    with patch("smtplib.SMTP_SSL") as smtp_cls:
        smtp_inst = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp_inst
        impl.send(ctx)
        smtp_inst.login.assert_called_once_with("me@gmail.com", "xxxx yyyy zzzz aaaa")
        smtp_inst.send_message.assert_called_once()

    rec = ctx.meta["destinations"]["email"][0]
    assert rec["subject"] == "【議事録】Weekly"
    assert "a@example.com" in rec["recipients"]
    assert "b@example.com" in rec["recipients"]


def test_send_missing_env_raises(monkeypatch, minimal_cassette, tmp_path):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    impl = EmailDestinationImpl(EmailDestination(to=["x@y.z"], subject="s"))
    ctx = Context(input_path=tmp_path / "s", cassette=minimal_cassette)
    with pytest.raises(EnvironmentError):
        impl.send(ctx)
