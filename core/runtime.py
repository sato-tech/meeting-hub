"""Step 実行ランタイム（Phase 3）。

- `local`:  現在のプロセスで直接 Step.process(ctx) を呼ぶ
- `modal`:  Modal Labs の GPU コンテナ上で重い推論だけ実行

カセット YAML の `pipeline[].runtime` を参照して `get_runtime(name)` で選ぶ。
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.context import Context
    from core.steps.base import Step

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Runtime 抽象・レジストリ
# ═══════════════════════════════════════════════════
class RuntimeAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def execute(self, step: "Step", ctx: "Context") -> "Context":
        """Step をランタイム上で実行する。"""


_registry: dict[str, RuntimeAdapter] = {}


def register_runtime(name: str, runtime: RuntimeAdapter) -> None:
    _registry[name] = runtime


def get_runtime(name: str) -> RuntimeAdapter:
    """登録済みランタイムを返す。無ければ local にフォールバック + warning。"""
    if name in _registry:
        return _registry[name]
    logger.warning("runtime=%r not registered; falling back to local", name)
    return _registry["local"]


def list_runtimes() -> list[str]:
    return sorted(_registry.keys())


# ═══════════════════════════════════════════════════
# LocalRuntime
# ═══════════════════════════════════════════════════
class LocalRuntime(RuntimeAdapter):
    name = "local"

    def execute(self, step: "Step", ctx: "Context") -> "Context":
        return step.process(ctx)


# ═══════════════════════════════════════════════════
# ModalRuntime
# ═══════════════════════════════════════════════════
MODAL_APP_NAME = os.environ.get("MEETING_HUB_MODAL_APP", "meeting-hub")
MODAL_SUPPORTED_STEPS = {"transcribe", "diarize"}


class ModalRuntime(RuntimeAdapter):
    """重い推論 Step を Modal Labs 上で実行。

    - Phase 3 スコープは `transcribe` / `diarize` のみ対応
    - Modal 関数は `scripts/modal_deploy.py` で deploy
    - modal 未 install / lookup 失敗時はフォールバックで local 実行 + warning
    - 音声は bytes で送信（Modal volume 経由は Phase 4 以降）
    """

    name = "modal"

    def __init__(self):
        self._lookup_cache: dict[str, Any] = {}

    def _get_remote_fn(self, step_name: str):
        if step_name in self._lookup_cache:
            return self._lookup_cache[step_name]
        try:
            import modal  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("modal SDK not installed — cannot run on Modal")
            return None
        try:
            fn = modal.Function.lookup(MODAL_APP_NAME, f"{step_name}_on_modal")
        except Exception as e:
            logger.warning("modal lookup failed for %s: %s", step_name, e)
            return None
        self._lookup_cache[step_name] = fn
        return fn

    def execute(self, step: "Step", ctx: "Context") -> "Context":
        if step.name not in MODAL_SUPPORTED_STEPS:
            logger.info("modal runtime: step=%s not supported on modal, running local", step.name)
            return step.process(ctx)

        remote_fn = self._get_remote_fn(step.name)
        if remote_fn is None:
            ctx.add_warning(f"modal:unavailable:{step.name}")
            logger.warning("modal unavailable, falling back to local for step=%s", step.name)
            return step.process(ctx)

        audio_bytes = b""
        if ctx.audio_path and ctx.audio_path.exists():
            audio_bytes = ctx.audio_path.read_bytes()
        payload = {
            "audio_bytes": audio_bytes,
            "segments": list(ctx.segments),
            "params": dict(step.params),
            "provider": step.provider,
        }
        try:
            result = remote_fn.remote(**payload)
        except Exception as e:
            logger.exception("modal remote failed: %s", e)
            ctx.add_warning(f"modal:remote_error:{step.name}:{e}")
            return step.process(ctx)

        if not isinstance(result, dict):
            logger.warning("unexpected modal result type: %r", type(result))
            return step.process(ctx)

        if "segments" in result:
            ctx.segments = result["segments"]
        if "meta" in result:
            ctx.meta.setdefault(step.name, {}).update(result["meta"])
        ctx.meta.setdefault(step.name, {})["runtime"] = "modal"
        return ctx


# モジュール import で自動登録
register_runtime("local", LocalRuntime())
register_runtime("modal", ModalRuntime())


__all__ = [
    "RuntimeAdapter",
    "LocalRuntime",
    "ModalRuntime",
    "register_runtime",
    "get_runtime",
    "list_runtimes",
    "MODAL_APP_NAME",
    "MODAL_SUPPORTED_STEPS",
]
