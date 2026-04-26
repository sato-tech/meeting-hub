"""llm_cleanup Step — Claude による文字起こしテキスト整形。

設計（REPORT_PROMPT_B.md §3.5）:
  - chunking（予算内で無音ギャップ優先分割）
  - system prompt はファイルから（既定: prompts/cleanup_default.md、seminar: prompts/cleanup_seminar.md）
  - batch_mode=True は警告を出して False 扱い（§12-2 RESOLVED）
  - glossary addendum 対応（seminar-transcription 由来）
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.llm_client import ClaudeClient
from core.steps.base import Step

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"
_DEFAULT_SYSTEM_PROMPT = "prompts/cleanup_default.md"


# 文末記号（日本語・英語）。これで終わる segment の後を優先的に chunk 境界にする（B6）
_SENTENCE_END_CHARS = tuple("。！？!?.")


def _ends_with_sentence_terminator(text: str) -> bool:
    t = (text or "").rstrip()
    return t.endswith(_SENTENCE_END_CHARS)


def chunk_segments(
    segments: list[dict[str, Any]],
    max_chars: int = 12000,
    soft_chars: int = 8400,
    preferred_gap: float = 2.0,
    *,
    prefer_sentence_boundary: bool = True,
) -> list[list[dict[str, Any]]]:
    """Claude 出力予算内でセグメントを分割。

    - 基本は追加していき、soft_chars を超えたら:
      1. **文末記号で終わる** セグメントの後 → 最優先で区切る（B6、デフォルト有効）
      2. それが無ければ preferred_gap 以上の無音で区切る
    - max_chars を絶対に超えない（越えたら強制分割）

    `prefer_sentence_boundary=False` で従来挙動に戻せる。
    """
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    prev_end = 0.0
    prev_text = ""

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append(current)
            current = []
            current_len = 0

    for seg in segments:
        text_len = len(seg.get("text", ""))
        gap = float(seg["start"]) - prev_end

        should_flush_soft = current_len >= soft_chars
        at_sentence_end = prefer_sentence_boundary and _ends_with_sentence_terminator(prev_text)

        if should_flush_soft and at_sentence_end:
            # 文末で区切るのが最優先
            flush()
        elif should_flush_soft and gap >= preferred_gap:
            flush()
        elif current_len + text_len > max_chars:
            # 強制上限
            flush()

        current.append(seg)
        current_len += text_len
        prev_end = float(seg["end"])
        prev_text = seg.get("text", "")

    flush()
    return chunks


def format_chunk_as_text(chunk: list[dict[str, Any]], include_timestamps: bool = True) -> str:
    """チャンクを Claude に渡すための text 化。"""
    lines: list[str] = []
    for seg in chunk:
        ts = ""
        if include_timestamps:
            m = int(float(seg["start"]) // 60)
            s = int(float(seg["start"]) % 60)
            ts = f"[{m:02d}:{s:02d}] "
        speaker = seg.get("speaker") or ""
        prefix = f"{speaker}: " if speaker and speaker != "未割当" else ""
        lines.append(f"{ts}{prefix}{seg.get('text', '')}")
    return "\n".join(lines)


@Step.register("llm_cleanup", "claude")
class ClaudeCleanupStep(Step):
    """Claude Haiku でテキスト整形。

    params:
      preserve_original (bool, default True)
      remove_fillers (bool, default True)
      insert_punctuation (bool, default False)
      system_prompt_path (str, optional)
      chunk_max_chars (int, default 12000)
      chunk_soft_chars (int, default 8400)
      preferred_gap (float, default 2.0)
      glossary_path (str, optional): 用語対応表ファイル（seminar 由来）
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

    def _should_use_batch(self, ctx: Context, chunk_count: int) -> bool:
        """Batch API 採用条件（Phase 3、§12-2 RESOLVED で解禁）。

        - cassette.llm.batch_mode=true
        - cassette.mode in {cloud_batch, cloud}
        - chunk_count >= 2（単発なら messages API が早い）
        """
        llm = ctx.cassette.llm
        if not llm.batch_mode:
            return False
        if ctx.cassette.mode not in ("cloud_batch", "cloud"):
            return False
        return chunk_count >= 2

    def _load_system_prompt(self) -> str:
        path = self.params.get("system_prompt_path", _DEFAULT_SYSTEM_PROMPT)
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / path
        if not p.exists():
            raise FileNotFoundError(f"system prompt not found: {p}")
        return p.read_text(encoding="utf-8")

    def _load_glossary_addendum(self) -> str | None:
        gp = self.params.get("glossary_path")
        if not gp:
            return None
        p = Path(gp)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / gp
        if not p.exists():
            logger.warning("glossary_path not found: %s", p)
            return None
        pairs: list[tuple[str, str]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "->" in line:
                wrong, right = [x.strip() for x in line.split("->", 1)]
                pairs.append((wrong, right))
        if not pairs:
            return None
        body = "\n".join(f"- {w} → {r}" for w, r in pairs)
        return "## 用語の正規化（以下を優先して置換）\n" + body

    def process(self, ctx: Context) -> Context:
        if not ctx.segments:
            logger.warning("llm_cleanup skipped: no segments")
            return ctx

        t0 = time.monotonic()
        client = self._get_client(ctx)
        system = self._load_system_prompt()
        addendum = self._load_glossary_addendum()

        max_c = int(self.params.get("chunk_max_chars", 12000))
        soft_c = int(self.params.get("chunk_soft_chars", 8400))
        gap = float(self.params.get("preferred_gap", 2.0))

        chunks = chunk_segments(ctx.segments, max_c, soft_c, gap)
        use_batch = self._should_use_batch(ctx, len(chunks))
        cleaned_parts: list[str] = []

        if use_batch:
            logger.info("llm_cleanup: using Batch API for %d chunks (50%% discount)", len(chunks))
            user_contents = [format_chunk_as_text(c) for c in chunks]
            try:
                cleaned_parts = client.complete_batch(
                    system_prompt=system,
                    user_contents=user_contents,
                    extra_system_suffix=addendum,
                )
            except Exception as e:
                logger.warning("Batch API failed (%s); falling back to messages API", e)
                ctx.add_warning(f"llm_cleanup:batch_fallback:{e}")
                cleaned_parts = []  # 通常 API で再処理

        if not cleaned_parts:
            for i, chunk in enumerate(chunks, 1):
                user_content = format_chunk_as_text(chunk)
                logger.info("llm_cleanup chunk %d/%d (%d chars)", i, len(chunks), len(user_content))
                text = client.complete(
                    system_prompt=system,
                    user_content=user_content,
                    extra_system_suffix=addendum,
                )
                cleaned_parts.append(text)

        ctx.cleaned_text = "\n\n".join(cleaned_parts)
        ctx.meta.setdefault("llm_cleanup", {}).update(
            {
                "provider": self.provider,
                "model": ctx.cassette.llm.model,
                "chunks": len(chunks),
                "tokens_in": client.usage.input_tokens,
                "tokens_out": client.usage.output_tokens,
                "mode": "batch" if use_batch and cleaned_parts else "messages",
            }
        )
        ctx.record_timing("llm_cleanup", time.monotonic() - t0)
        logger.info("[5/N] llm_cleanup: %d chunks, %d in / %d out tokens",
                    len(chunks), client.usage.input_tokens, client.usage.output_tokens)
        return ctx


@Step.register("llm_cleanup", "none")
class NoopCleanupStep(Step):
    """LLM を使わない（mode=local の 1on1 等で選択可能）。"""

    default_provider = "none"

    def process(self, ctx: Context) -> Context:
        ctx.cleaned_text = format_chunk_as_text(ctx.segments) if ctx.segments else ""
        ctx.meta.setdefault("llm_cleanup", {})["provider"] = "none"
        return ctx
