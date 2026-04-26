"""RuntimeAdapter の選択ロジックテスト。"""
from __future__ import annotations

import pytest

from core.context import Context
from core.runtime import (
    LocalRuntime,
    ModalRuntime,
    RuntimeAdapter,  # noqa: F401
    get_runtime,
    register_runtime,  # noqa: F401
)
from core.steps.base import Step


def test_local_runtime_is_registered() -> None:
    assert isinstance(get_runtime("local"), LocalRuntime)


def test_modal_runtime_is_registered() -> None:
    assert isinstance(get_runtime("modal"), ModalRuntime)


def test_unknown_runtime_falls_back_to_local(caplog) -> None:
    r = get_runtime("nonexistent_xxx")
    assert isinstance(r, LocalRuntime)


def test_modal_runtime_falls_back_on_unsupported_step(minimal_cassette, tmp_path, monkeypatch):
    """非対応 Step (preprocess) は local で実行される。"""

    @Step.register("preprocess", "_modal_runtime_test")
    class P(Step):
        def process(self, ctx: Context) -> Context:
            ctx.meta["ran_local"] = True
            return ctx

    step = P(provider="_modal_runtime_test", params={})
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)

    runtime = ModalRuntime()
    ctx = runtime.execute(step, ctx)
    assert ctx.meta.get("ran_local") is True


def test_modal_runtime_warns_when_sdk_missing(monkeypatch, minimal_cassette, tmp_path):
    """modal が未 install / lookup 失敗時はフォールバック + warning を記録。"""

    @Step.register("transcribe", "_modal_runtime_test_fallback")
    class T(Step):
        def process(self, ctx: Context) -> Context:
            ctx.meta["fallback_ran"] = True
            return ctx

    runtime = ModalRuntime()
    # lookup を強制失敗
    monkeypatch.setattr(runtime, "_get_remote_fn", lambda step_name: None)

    step = T(provider="_modal_runtime_test_fallback", params={})
    ctx = Context(input_path=tmp_path / "x", cassette=minimal_cassette)
    ctx = runtime.execute(step, ctx)
    assert ctx.meta.get("fallback_ran") is True
    assert any("modal:unavailable" in w for w in ctx.meta.get("warnings", []))
