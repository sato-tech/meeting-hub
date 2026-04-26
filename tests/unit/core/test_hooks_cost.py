"""hooks.aggregate_claude_usage / log_summary のテスト（T7 / B7）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.hooks import aggregate_claude_usage, log_summary


def test_aggregate_claude_usage_no_steps(minimal_cassette):
    ctx = Context(input_path=Path("/tmp/x"), cassette=minimal_cassette)
    u = aggregate_claude_usage(ctx)
    assert u == {"input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0}


def test_aggregate_claude_usage_sums_steps(minimal_cassette):
    ctx = Context(input_path=Path("/tmp/x"), cassette=minimal_cassette)
    ctx.meta["llm_cleanup"] = {"tokens_in": 10000, "tokens_out": 2000}
    ctx.meta["minutes_extract"] = {"tokens_in": 5000, "tokens_out": 1000}
    u = aggregate_claude_usage(ctx)
    assert u["input_tokens"] == 15000
    assert u["output_tokens"] == 3000
    # 15000 * 1.0 / 1e6 + 3000 * 5.0 / 1e6 = 0.015 + 0.015 = 0.030
    assert abs(u["estimated_usd"] - 0.030) < 0.0001


def test_log_summary_records_claude_total_in_meta(minimal_cassette, caplog):
    ctx = Context(input_path=Path("/tmp/x"), cassette=minimal_cassette)
    ctx.meta["llm_cleanup"] = {"tokens_in": 100, "tokens_out": 50}
    log_summary(ctx)
    assert "claude_total" in ctx.meta
    assert ctx.meta["claude_total"]["input_tokens"] == 100


def test_log_summary_skips_claude_when_zero(minimal_cassette):
    ctx = Context(input_path=Path("/tmp/x"), cassette=minimal_cassette)
    log_summary(ctx)
    assert "claude_total" not in ctx.meta
