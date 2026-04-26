"""パイプライン前後のフック。

Pre-hooks: 環境確認・入力バリデーション
Post-hooks: サマリログ・品質チェック
"""
from __future__ import annotations

import logging
import os
import shutil

from core.context import Context

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Pre-hooks
# ═══════════════════════════════════════════════════
def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise EnvironmentError("ffmpeg not found in PATH")


def validate_input(ctx: Context) -> None:
    p = ctx.input_path
    if not p.exists():
        raise FileNotFoundError(f"Input not found: {p}")
    if p.stat().st_size == 0:
        raise ValueError(f"Input is empty: {p}")
    allowed = set(ctx.cassette.input.supported_formats)
    if p.suffix.lower().lstrip(".") not in allowed:
        logger.warning(
            "Input extension %s not in cassette.supported_formats=%s",
            p.suffix, allowed,
        )


def validate_env(ctx: Context) -> None:
    diarize = ctx.cassette.get_step("diarize")
    if diarize and diarize.enabled and diarize.provider == "pyannote":
        if not os.environ.get("HUGGINGFACE_TOKEN"):
            raise EnvironmentError("HUGGINGFACE_TOKEN is required for pyannote diarize")
    for s in ctx.cassette.pipeline:
        if s.enabled and s.provider == "claude":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise EnvironmentError("ANTHROPIC_API_KEY is required for claude provider")
            break


def run_pre_hooks(ctx: Context) -> None:
    check_ffmpeg()
    validate_input(ctx)
    validate_env(ctx)
    logger.info("pre-hooks OK")


# ═══════════════════════════════════════════════════
# Post-hooks
# ═══════════════════════════════════════════════════
# Claude Haiku 4.5 の料金（USD / MTok）。将来の値上げ時はここを更新。
_CLAUDE_INPUT_USD_PER_MTOK = 1.00
_CLAUDE_OUTPUT_USD_PER_MTOK = 5.00


def aggregate_claude_usage(ctx: Context) -> dict[str, float]:
    """ctx.meta の各 Claude step（llm_cleanup / minutes_extract）の tokens を合算。

    戻り値:
      {"input_tokens": int, "output_tokens": int, "estimated_usd": float}
    """
    in_tok = 0
    out_tok = 0
    for step_name in ("llm_cleanup", "minutes_extract"):
        meta = ctx.meta.get(step_name) or {}
        in_tok += int(meta.get("tokens_in", 0) or 0)
        out_tok += int(meta.get("tokens_out", 0) or 0)
    usd = (
        in_tok / 1_000_000 * _CLAUDE_INPUT_USD_PER_MTOK
        + out_tok / 1_000_000 * _CLAUDE_OUTPUT_USD_PER_MTOK
    )
    return {"input_tokens": in_tok, "output_tokens": out_tok, "estimated_usd": round(usd, 6)}


def log_summary(ctx: Context) -> None:
    logger.info("=" * 50)
    logger.info("Summary for run_id=%s", ctx.run_id)
    logger.info("  Input:        %s", ctx.input_path)
    logger.info("  Audio:        %s", ctx.audio_path)
    logger.info("  Segments:     %d", len(ctx.segments))
    logger.info("  Outputs:      %s", list(ctx.outputs.keys()))
    for step, sec in (ctx.meta.get("timings") or {}).items():
        logger.info("  [%s] %.1fs", step, sec)

    usage = aggregate_claude_usage(ctx)
    if usage["input_tokens"] or usage["output_tokens"]:
        logger.info(
            "  Claude total: in=%d out=%d  (est. $%.4f)",
            usage["input_tokens"],
            usage["output_tokens"],
            usage["estimated_usd"],
        )
        # meta に保存して destinations / UI 側で参照できるように
        ctx.meta["claude_total"] = usage

    if ctx.meta.get("warnings"):
        for w in ctx.meta["warnings"]:
            logger.warning("  ! %s", w)

    for w in quality_check(ctx):
        logger.warning("  [quality] %s", w)


def quality_check(ctx: Context) -> list[str]:
    warnings: list[str] = []
    if not ctx.segments:
        warnings.append("no segments produced")
        return warnings
    unknown_ratio = sum(1 for s in ctx.segments if s.get("speaker") in ("UNKNOWN", "未割当"))
    ratio = unknown_ratio / len(ctx.segments)
    if ratio > 0.3:
        warnings.append(f"unknown/unassigned speaker ratio high: {ratio:.0%}")
    short = sum(1 for s in ctx.segments if float(s["end"]) - float(s["start"]) < 0.5)
    if short > 0.5 * len(ctx.segments):
        warnings.append(f"many short segments: {short}/{len(ctx.segments)}")
    return warnings
