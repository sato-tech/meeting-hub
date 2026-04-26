"""回帰テスト用メトリクス計算（REPORT_PROMPT_C.md §4 対応）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.context import Context


def metrics_from_context(ctx: Context) -> dict[str, Any]:
    """Pipeline 実行後の Context からメトリクス dict を生成。"""
    segs = ctx.segments or []
    dist: dict[str, int] = {}
    for s in segs:
        sp = s.get("speaker", "UNKNOWN")
        dist[sp] = dist.get(sp, 0) + 1
    return {
        "sample_id": ctx.run_id,
        "source": "meeting-hub",
        "segment_count": len(segs),
        "speaker_distribution": dist,
        "total_chars": sum(len(s.get("text", "")) for s in segs),
        "time_range_sec": {
            "start": float(segs[0]["start"]) if segs else 0.0,
            "end": float(segs[-1]["end"]) if segs else 0.0,
        },
        "term_correct_applied": (ctx.meta.get("term_correct") or {}).get("applied_count", 0),
        "has_minutes": ctx.minutes is not None,
    }


def metrics_from_golden_dir(sample_dir: Path) -> dict[str, Any]:
    """ゴールデンサンプルの metrics.json を読む。"""
    p = sample_dir / "metrics.json"
    return json.loads(p.read_text(encoding="utf-8"))


def within_tolerance(golden: Any, actual: Any, tol: float) -> bool:
    """数値比較（相対誤差 tol<1.0 / 絶対誤差 tol>=1）。"""
    if isinstance(tol, float) and 0 < tol < 1.0:
        return abs(actual - golden) <= max(1, abs(golden)) * tol
    return abs(actual - golden) <= tol
