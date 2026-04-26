"""Claude API の共通低レベルクライアント（cleanup / extract で共有）。

§12-2 RESOLVED: Phase 1 は messages API 直通。Batch API は Phase 3。
§12-9 RESOLVED: テストは `anthropic` SDK を monkeypatch で fake に差替。

Phase 3 で `complete_batch(system, user_contents)` を追加、Batch API で 50%割引・
最大 24h 以内処理（中央値 ~5 分）を実現。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Batch API のポーリング設定
BATCH_POLL_INTERVAL_SEC = 15
BATCH_MAX_WAIT_SEC = 3600  # 最大 1 時間待機（実測の中央値は 5 分）


@dataclass
class ClaudeUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_t: int, output_t: int) -> None:
        self.input_tokens += int(input_t)
        self.output_tokens += int(output_t)


@dataclass
class ClaudeClient:
    """anthropic SDK の薄いラッパ。"""

    model: str = "claude-haiku-4-5"
    max_tokens: int = 8192
    max_retries: int = 3
    base_backoff: float = 2.0
    cache_strategy: str = "system_prompt"  # "none" | "system_prompt" | "full"
    usage: ClaudeUsage = field(default_factory=ClaudeUsage)
    _client: Any = None
    _anthropic: Any = None

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise EnvironmentError("ANTHROPIC_API_KEY is not set.")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int | None = None,
        extra_system_suffix: str | None = None,
    ) -> str:
        """messages.create を叩いてテキストを返す。リトライ付き。"""
        self._ensure_client()
        system = system_prompt
        if extra_system_suffix:
            system = system + "\n\n" + extra_system_suffix

        # cache_strategy=system_prompt なら system を cache_control 対象に
        if self.cache_strategy in ("system_prompt", "full"):
            system_blocks: list[dict[str, Any]] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_blocks = [{"type": "text", "text": system}]

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_content}],
                )
                text = self._extract_text(resp)
                self._record_usage(resp)
                return text
            except Exception as e:
                last_err = e
                if self._is_rate_limit(e):
                    wait = self.base_backoff ** attempt
                    logger.warning("RateLimit retry %d/%d (sleep %ss)", attempt, self.max_retries, wait)
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Claude API failed after {self.max_retries} retries: {last_err}")

    @staticmethod
    def _extract_text(resp: Any) -> str:
        # SDK のレスポンス構造: resp.content は list[ContentBlock]、通常 text ブロック 1 個
        content = getattr(resp, "content", None) or []
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()

    def _record_usage(self, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        self.usage.add(
            getattr(usage, "input_tokens", 0),
            getattr(usage, "output_tokens", 0),
        )

    # ─── Structured Output（Phase 6 / T4） ──────────
    def complete_json(
        self,
        system_prompt: str,
        user_content: str,
        *,
        tool_name: str = "record_minutes",
        tool_description: str = "議事録の構造化データを記録する",
        input_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        extra_system_suffix: str | None = None,
    ) -> dict[str, Any]:
        """tool_use 経由で構造化 JSON を保証して取得する。

        Claude の tool_use は input_schema に沿った JSON を必ず返すため、
        従来の「テキスト → regex で JSON 抽出 → parse」より堅牢。

        失敗時（RateLimit など）は通常の retry を行う。パースエラーは原理的に起きない。
        """
        self._ensure_client()
        system = system_prompt
        if extra_system_suffix:
            system = system + "\n\n" + extra_system_suffix

        if self.cache_strategy in ("system_prompt", "full"):
            system_blocks: list[dict[str, Any]] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_blocks = [{"type": "text", "text": system}]

        schema = input_schema or {
            "type": "object",
            "description": "議事録の構造化オブジェクト。プロンプトで指定された形式で任意のキーを含めること。",
            "additionalProperties": True,
        }

        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": schema,
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    system=system_blocks,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                    messages=[{"role": "user", "content": user_content}],
                )
                self._record_usage(resp)
                # content は ToolUseBlock を含むリスト
                content = getattr(resp, "content", None) or []
                for block in content:
                    if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                        payload = getattr(block, "input", None)
                        if isinstance(payload, dict):
                            return payload
                raise RuntimeError("tool_use block not found in Claude response")
            except Exception as e:
                last_err = e
                if self._is_rate_limit(e):
                    wait = self.base_backoff ** attempt
                    logger.warning("RateLimit retry %d/%d (sleep %ss)", attempt, self.max_retries, wait)
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Claude tool_use failed after {self.max_retries} retries: {last_err}")

    def _is_rate_limit(self, e: Exception) -> bool:
        """RateLimitError 判定の防御的ヘルパ（テストで Mock が入っても落ちない）。"""
        if not self._anthropic:
            return False
        cls = getattr(self._anthropic, "RateLimitError", None)
        if not isinstance(cls, type):
            return False
        return isinstance(e, cls)

    # ─── Batch API（Phase 3） ──────────────────────
    def complete_batch(
        self,
        system_prompt: str,
        user_contents: list[str],
        *,
        max_tokens: int | None = None,
        extra_system_suffix: str | None = None,
        poll_interval_sec: int = BATCH_POLL_INTERVAL_SEC,
        max_wait_sec: int = BATCH_MAX_WAIT_SEC,
    ) -> list[str]:
        """Batch API でまとめて推論し、結果テキストを元の順序で返す。

        50% 割引。結果は最大 24h 以内（中央値 5 分）に出る。失敗時は RuntimeError。
        """
        if not user_contents:
            return []

        self._ensure_client()
        system = system_prompt
        if extra_system_suffix:
            system = system + "\n\n" + extra_system_suffix

        if self.cache_strategy in ("system_prompt", "full"):
            system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        else:
            system_blocks = [{"type": "text", "text": system}]

        # リクエスト組立
        custom_ids = [f"req-{i}-{uuid.uuid4().hex[:8]}" for i in range(len(user_contents))]
        requests_payload = [
            {
                "custom_id": cid,
                "params": {
                    "model": self.model,
                    "max_tokens": max_tokens or self.max_tokens,
                    "system": system_blocks,
                    "messages": [{"role": "user", "content": uc}],
                },
            }
            for cid, uc in zip(custom_ids, user_contents)
        ]

        # Batch 送信 → polling → 結果取得
        batch = self._client.messages.batches.create(requests=requests_payload)
        batch_id = getattr(batch, "id", None) or batch["id"]
        logger.info("Batch API submitted: id=%s size=%d", batch_id, len(user_contents))

        waited = 0
        while waited < max_wait_sec:
            status_obj = self._client.messages.batches.retrieve(batch_id)
            status = getattr(status_obj, "processing_status", None) or status_obj.get("processing_status")
            if status == "ended":
                break
            if status in ("canceling", "cancelled", "expired"):
                raise RuntimeError(f"Batch {batch_id} ended abnormally: {status}")
            logger.info("Batch %s status=%s (waited=%ds)", batch_id, status, waited)
            time.sleep(poll_interval_sec)
            waited += poll_interval_sec
        else:
            raise RuntimeError(f"Batch {batch_id} did not complete within {max_wait_sec}s")

        # 結果を取得
        results_iter = self._client.messages.batches.results(batch_id)
        by_id: dict[str, str] = {}
        usage_in = usage_out = 0
        for item in results_iter:
            cid = getattr(item, "custom_id", None) or item.get("custom_id")
            result = getattr(item, "result", None) or item.get("result")
            if not result:
                continue
            rtype = getattr(result, "type", None) or result.get("type")
            if rtype != "succeeded":
                logger.warning("Batch item %s failed: %s", cid, result)
                by_id[cid] = ""
                continue
            message = getattr(result, "message", None) or result.get("message")
            text = self._extract_text(message)
            usage = getattr(message, "usage", None) or (message.get("usage") if isinstance(message, dict) else None)
            if usage:
                usage_in += int(getattr(usage, "input_tokens", 0) or (usage.get("input_tokens", 0) if isinstance(usage, dict) else 0))
                usage_out += int(getattr(usage, "output_tokens", 0) or (usage.get("output_tokens", 0) if isinstance(usage, dict) else 0))
            by_id[cid] = text

        self.usage.add(usage_in, usage_out)
        ordered = [by_id.get(cid, "") for cid in custom_ids]
        logger.info("Batch %s completed: %d results, tokens in=%d out=%d", batch_id, len(ordered), usage_in, usage_out)
        return ordered
