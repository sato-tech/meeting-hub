"""Step ABC と Provider レジストリ。

設計決定（REPORT_PROMPT_B.md §2）:
  - `Step.process(ctx: Context) -> Context` の単純IF
  - provider は `Step.register(name, provider)` デコレータで自動登録
  - `Step.create(step_cfg)` がファクトリ（CassetteConfig.pipeline から生成）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from core.cassette_schema import StepConfig, StepName
from core.context import Context


class Step(ABC):
    """全 Step の基底クラス。"""

    name: ClassVar[StepName]
    default_provider: ClassVar[str | None] = None

    # (name, provider) → Step サブクラスのマップ
    _registry: ClassVar[dict[tuple[StepName, str], type["Step"]]] = {}

    def __init__(self, provider: str | None, params: dict[str, Any]):
        self.provider = provider or self.default_provider or "default"
        self.params = params or {}

    @abstractmethod
    def process(self, ctx: Context) -> Context:
        """Context を mutate して返す。"""

    def on_error(self, ctx: Context, exc: Exception) -> None:
        """既定は meta.errors に記録のみ（再送出は呼び出し側で）。"""
        ctx.meta.setdefault("errors", []).append(
            {"step": self.name, "provider": self.provider, "error": repr(exc)}
        )

    # ─── レジストリ ──────────────────────────────
    @classmethod
    def register(cls, name: StepName, provider: str):
        """`@Step.register("preprocess", "default")` で Step 実装を登録する。"""

        def deco(sub: type[Step]) -> type[Step]:
            sub.name = name  # type: ignore[assignment]
            cls._registry[(name, provider)] = sub
            return sub

        return deco

    @classmethod
    def create(cls, step_cfg: StepConfig) -> "Step":
        provider = step_cfg.provider or _implicit_default(step_cfg.step)
        key = (step_cfg.step, provider)
        if key not in cls._registry:
            raise ValueError(
                f"No Step implementation registered for {key}. "
                f"Known: {sorted(cls._registry.keys())}"
            )
        return cls._registry[key](provider, step_cfg.params)

    @classmethod
    def is_registered(cls, name: StepName, provider: str) -> bool:
        return (name, provider) in cls._registry

    @classmethod
    def clear_registry(cls) -> None:
        """テスト専用: レジストリを空にする。"""
        cls._registry.clear()


def _implicit_default(step: StepName) -> str:
    """provider 未指定時の暗黙既定値。カセットで provider 必須な Step 以外で使用。"""
    return {
        "preprocess": "default",
        "term_correct": "regex",
        "format": "default",
    }.get(step, "default")
