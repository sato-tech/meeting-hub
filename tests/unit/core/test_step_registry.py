"""Step レジストリの挙動確認。"""
from __future__ import annotations

from typing import Any

import pytest

from core.cassette_schema import StepConfig
from core.context import Context
from core.steps.base import Step


class _DummyStep(Step):
    def process(self, ctx: Context) -> Context:
        ctx.meta["dummy"] = True
        return ctx


def test_register_and_create(minimal_cassette) -> None:
    # 既存登録を壊さないよう、専用 (step, provider) ペアを使う
    @Step.register("preprocess", "_test_provider")
    class X(_DummyStep):
        pass

    cfg = StepConfig(step="preprocess", provider="_test_provider", params={"a": 1})
    step = Step.create(cfg)
    assert isinstance(step, X)
    assert step.params == {"a": 1}


def test_create_unknown_raises() -> None:
    cfg = StepConfig(step="transcribe", provider="_not_registered_zzz", params={})
    with pytest.raises(ValueError, match="No Step implementation"):
        Step.create(cfg)


def test_name_is_set_on_registered_class() -> None:
    @Step.register("term_correct", "_test_regex_v2")
    class Y(_DummyStep):
        pass

    assert Y.name == "term_correct"
