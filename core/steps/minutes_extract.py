"""minutes_extract Step — Claude による議事録構造化抽出（Phase 1 新規）。

設計（REPORT_PROMPT_B.md §3.6）:
  - prompts/minutes_extract_{cassette}.md を system prompt として使用
  - user content は ctx.cleaned_text（なければ segments join）
  - JSON 出力を要求、parse 失敗時は 1 回 retry（厳格化プロンプト追加）
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.llm_client import ClaudeClient
from core.steps.base import Step
from core.steps.llm_cleanup import format_chunk_as_text

logger = logging.getLogger(__name__)


def _extract_json_block(text: str) -> str:
    """応答文字列から最初の JSON オブジェクトを抜き出す。

    ```json ... ``` や前後の説明文にも耐性を持たせる。
    """
    # ```json ... ``` を優先
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # 最外 { ... } をバランシング（シンプル）
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    return text.strip()


@Step.register("minutes_extract", "claude")
class ClaudeMinutesExtractStep(Step):
    """カセット別の議事録抽出。

    params:
      prompt (str): prompts/minutes_extract_*.md のパス（cassette で指定）
      template (str, optional): Jinja2 テンプレ（format で使うが参照用にメタに記録）
      extract_chapters (bool, default False): seminar 向けの章立て抽出
      output_json_schema (dict, optional): strict mode 用
    """

    default_provider = "claude"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._client: ClaudeClient | None = None

    def _get_client(self, ctx: Context) -> ClaudeClient:
        if self._client is not None:
            return self._client
        llm = ctx.cassette.llm
        self._client = ClaudeClient(
            model=llm.model,
            max_tokens=llm.max_tokens,
            cache_strategy=llm.cache_strategy,
        )
        return self._client

    def _load_prompt(self) -> str:
        path = self.params.get("prompt")
        if not path:
            raise ValueError("minutes_extract requires `prompt` param (path to system prompt)")
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / path
        if not p.exists():
            raise FileNotFoundError(f"minutes prompt not found: {p}")
        return p.read_text(encoding="utf-8")

    def _build_user_content(self, ctx: Context) -> str:
        if ctx.cleaned_text:
            return ctx.cleaned_text
        if ctx.segments:
            return format_chunk_as_text(ctx.segments)
        raise RuntimeError("minutes_extract: no cleaned_text nor segments available")

    def _parse_json(self, text: str) -> dict[str, Any]:
        block = _extract_json_block(text)
        try:
            return json.loads(block)
        except json.JSONDecodeError as e:
            logger.warning("minutes_extract JSON parse failed: %s", e)
            raise

    def process(self, ctx: Context) -> Context:
        t0 = time.monotonic()
        client = self._get_client(ctx)
        system = self._load_prompt()
        user_content = self._build_user_content(ctx)

        use_structured = bool(self.params.get("use_structured_output", False))
        mode = "text"
        minutes: dict[str, Any] = {}

        if use_structured:
            try:
                minutes = client.complete_json(
                    system_prompt=system,
                    user_content=user_content,
                    input_schema=self.params.get("output_json_schema"),
                )
                mode = "structured"
            except Exception as e:
                logger.warning(
                    "structured output failed (%s); falling back to text+parse", e
                )
                ctx.add_warning(f"minutes_extract:structured_fallback:{type(e).__name__}")
                use_structured = False

        if not use_structured:
            resp = client.complete(system_prompt=system, user_content=user_content)
            try:
                minutes = self._parse_json(resp)
            except json.JSONDecodeError:
                logger.info("Retrying minutes_extract with stricter JSON-only instruction")
                strict_suffix = (
                    "\n\n### 重要（再指示）\n"
                    "出力は **JSON オブジェクト 1 個のみ**。説明文・コードブロック記号を含めず、"
                    "{ から } までで完結させること。"
                )
                resp = client.complete(
                    system_prompt=system,
                    user_content=user_content,
                    extra_system_suffix=strict_suffix,
                )
                minutes = self._parse_json(resp)
                ctx.add_warning("minutes_extract:retry_for_json")

        ctx.minutes = minutes
        ctx.meta.setdefault("minutes_extract", {}).update(
            {
                "provider": self.provider,
                "model": ctx.cassette.llm.model,
                "keys": sorted(minutes.keys()),
                "tokens_in": client.usage.input_tokens,
                "tokens_out": client.usage.output_tokens,
                "mode": mode,
            }
        )
        ctx.record_timing("minutes_extract", time.monotonic() - t0)
        logger.info("[6/N] minutes_extract: %d keys (mode=%s)", len(minutes), mode)
        return ctx
