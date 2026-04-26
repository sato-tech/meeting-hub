"""Claude Batch API のテスト（anthropic SDK は fake）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.llm_client import ClaudeClient


def _make_fake_message(text: str, in_tok: int = 10, out_tok: int = 20):
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    msg.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)
    return msg


def test_complete_batch_empty_returns_empty():
    client = ClaudeClient()
    assert client.complete_batch("sys", []) == []


def test_complete_batch_polls_until_ended(monkeypatch):
    client = ClaudeClient(max_tokens=100)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    # fake anthropic SDK
    fake_module = MagicMock()
    fake_inst = MagicMock()
    fake_module.Anthropic = MagicMock(return_value=fake_inst)

    # batches.create → ID 返す
    fake_inst.messages.batches.create.return_value = MagicMock(id="bt_1")

    # retrieve: 1回目 in_progress → 2回目 ended
    status_seq = iter([
        MagicMock(processing_status="in_progress"),
        MagicMock(processing_status="ended"),
    ])
    fake_inst.messages.batches.retrieve.side_effect = lambda bid: next(status_seq)

    # results: custom_id 順に 2 件
    results = [
        MagicMock(
            custom_id="c0",
            result=MagicMock(type="succeeded", message=_make_fake_message("A", 1, 2)),
        ),
        MagicMock(
            custom_id="c1",
            result=MagicMock(type="succeeded", message=_make_fake_message("B", 3, 4)),
        ),
    ]
    fake_inst.messages.batches.results.return_value = iter(results)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    # 初回の custom_id は uuid で生成されるので、create 時に捕捉する
    captured = {}

    def fake_create(requests):
        captured["requests"] = requests
        return MagicMock(id="bt_1")

    fake_inst.messages.batches.create.side_effect = fake_create

    # results の custom_id を create の要求と揃える
    # （実装は create の結果を使うので、ここでは順序だけ合わせる）
    def fake_results(bid):
        reqs = captured["requests"]
        out = []
        for i, req in enumerate(reqs):
            text = "A" if i == 0 else "B"
            out.append(MagicMock(
                custom_id=req["custom_id"],
                result=MagicMock(type="succeeded", message=_make_fake_message(text, 1, 2)),
            ))
        return iter(out)

    fake_inst.messages.batches.results.side_effect = fake_results

    results_text = client.complete_batch(
        system_prompt="sys",
        user_contents=["first", "second"],
        poll_interval_sec=0,
        max_wait_sec=10,
    )
    assert results_text == ["A", "B"]
    assert client.usage.input_tokens == 2  # 1+1
    assert client.usage.output_tokens == 4  # 2+2


def test_complete_batch_raises_on_cancelled(monkeypatch):
    client = ClaudeClient()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    fake_module = MagicMock()
    fake_inst = MagicMock()
    fake_module.Anthropic = MagicMock(return_value=fake_inst)
    fake_inst.messages.batches.create.return_value = MagicMock(id="bt_1")
    fake_inst.messages.batches.retrieve.return_value = MagicMock(processing_status="cancelled")

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    with pytest.raises(RuntimeError, match="cancelled"):
        client.complete_batch("sys", ["x"], poll_interval_sec=0, max_wait_sec=10)
