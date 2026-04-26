"""term_correct Step — 用語辞書による regex 置換。

設計（REPORT_PROMPT_B.md §3.4）:
  - cassette.terms.stack = [business, it, company_acme] を後勝ちで合成
  - 各辞書は vocab/terms/{name}.yaml
  - 重複キーは warning を出す
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

from core.context import Context
from core.steps.base import Step

logger = logging.getLogger(__name__)

# リポジトリルートを推定（core/steps/term_correct.py → ../../）
_VOCAB_ROOT = Path(__file__).resolve().parents[2] / "vocab" / "terms"


def _load_one_dict(name: str, vocab_root: Path) -> list[dict[str, str]]:
    p = vocab_root / f"{name}.yaml"
    if not p.exists():
        logger.warning("terms file not found: %s", p)
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("patterns", []) or []


def load_term_stack(stack_names: list[str], vocab_root: Path | None = None) -> list[tuple[str, str]]:
    """後勝ちで積み上げた (regex, replace) タプル列を返す。

    重複した match（正規表現文字列完全一致）は warning を出し、後勝ちを採用。
    vocab_root=None のときはモジュール変数 `_VOCAB_ROOT` を動的に参照（テストの
    monkeypatch 対応）。
    """
    if vocab_root is None:
        import core.steps.term_correct as _self
        vocab_root = _self._VOCAB_ROOT
    merged: dict[str, str] = {}
    order: list[str] = []
    for name in stack_names:
        for entry in _load_one_dict(name, vocab_root):
            pat = entry.get("match")
            rep = entry.get("replace", "")
            if not pat:
                continue
            if pat in merged:
                logger.warning("Term pattern collision: %r (was %r, now %r)", pat, merged[pat], rep)
                merged[pat] = rep
            else:
                merged[pat] = rep
                order.append(pat)
    return [(p, merged[p]) for p in order]


@Step.register("term_correct", "regex")
class RegexTermCorrectStep(Step):
    """segments[].text に正規表現置換を適用する。

    params:
      extra_patterns (list[{match, replace}], optional): カセットで追加の上書き
    """

    default_provider = "regex"

    def process(self, ctx: Context) -> Context:
        t0 = time.monotonic()
        stack = list(ctx.cassette.terms.stack)
        patterns = load_term_stack(stack)

        extras = self.params.get("extra_patterns") or []
        for e in extras:
            if "match" in e:
                patterns.append((e["match"], e.get("replace", "")))

        compiled = [(re.compile(p), r) for p, r in patterns]

        applied = 0
        for seg in ctx.segments:
            text = seg.get("text", "")
            new = text
            for pat, rep in compiled:
                new, n = pat.subn(rep, new)
                applied += n
            seg["text"] = new

        ctx.meta.setdefault("term_correct", {}).update(
            {
                "provider": self.provider,
                "applied_count": applied,
                "stack": stack,
                "pattern_count": len(compiled),
            }
        )
        ctx.record_timing("term_correct", time.monotonic() - t0)
        # 既存リポ互換のログ
        logger.info("[用語補正] 完了: %d件", applied)
        return ctx
