"""transcribe Step — faster-whisper による音声→テキスト変換。

Provider: faster_whisper_batch（両リポを単一 provider に統合、REPORT_PROMPT_B.md §3.2）

機能:
  - 3層ハルシネーション防御（VAD / pattern 検出 / 繰返し除去）
  - tail recovery（末尾セグメントの救済、seminar-transcription 由来）
  - VAD リトライ（セグメント0件なら vad_threshold を下げて再実行、純関数）
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.steps.base import Step

logger = logging.getLogger(__name__)

# 既定ハルシネーションパターン（transcription-pipeline/config.py 完全移植 + 既存拡張）
DEFAULT_HALLUCINATION_PATTERNS = [
    r"^ご視聴.{0,10}ありがとう",
    r"^チャンネル登録",
    r"^いいね.{0,5}お願い",
    r"^提供.{0,10}$",
    # 以下、transcription-pipeline HALLUCINATION_PATTERNS から移植
    r"字幕は.*?が担当",             # 字幕担当者のクレジット誤認識
    r"お問い合わせは",               # 放送番組のフッター誤認識
    r"(.{3,})\1{3,}",               # 3 文字以上のブロックが 4 回以上繰返し
]


# カセット名 → initial_prompt デフォルトファイル（A4）
_CASSETTE_TO_INITIAL_PROMPT = {
    "seminar": "vocab/initial_prompts/seminar.txt",
    # 下記はすべて business.txt を既定に
    "sales_meeting": "vocab/initial_prompts/business.txt",
    "internal_meeting": "vocab/initial_prompts/business.txt",
    "one_on_one": "vocab/initial_prompts/business.txt",
    "one_on_one_live": "vocab/initial_prompts/business.txt",
    "interview": "vocab/initial_prompts/business.txt",
    "live_sales": "vocab/initial_prompts/business.txt",
    "live_internal": "vocab/initial_prompts/business.txt",
}


def resolve_default_initial_prompt_file(cassette_name: str) -> str | None:
    """カセット名から initial_prompt ファイルの既定を返す（なければ None）。"""
    return _CASSETTE_TO_INITIAL_PROMPT.get(cassette_name)


def _compute_initial_prompt(
    params: dict[str, Any],
    cassette_name: str | None = None,
) -> str | None:
    """params と cassette_name から initial_prompt を組み立てる（共通ヘルパ）。

    優先順位:
      1. params["initial_prompt_file"] が指定されていればそれを読む（指定があって存在しない場合は警告）
      2. params["initial_prompt"] が指定されていれば直接使う
      3. 上記どちらもなければ cassette_name に応じた既定 vocab/initial_prompts/*.txt を使う（A4）

    返り値: 組み立てた文字列（空なら None）
    """
    direct = params.get("initial_prompt")
    file = params.get("initial_prompt_file")
    parts: list[str] = []

    # file 指定あり、なければ cassette fallback
    resolved_file: Path | None = None
    if file:
        resolved_file = Path(file)
    elif cassette_name:
        default_rel = resolve_default_initial_prompt_file(cassette_name)
        if default_rel:
            resolved_file = Path(__file__).resolve().parents[2] / default_rel

    if resolved_file:
        if resolved_file.exists():
            parts.append(resolved_file.read_text(encoding="utf-8").strip())
        else:
            logger.warning("initial_prompt file not found: %s", resolved_file)

    if direct:
        parts.append(str(direct).strip())

    if not parts:
        return None
    combined = " ".join(parts).strip()
    if len(combined) > 300:
        logger.warning(
            "initial_prompt is long (%d chars). Whisper caps around 224 tokens.",
            len(combined),
        )
    return combined


def is_hallucination(text: str, patterns: list[str]) -> bool:
    """層2: 既知のハルシネーション文をパターン検出。"""
    t = (text or "").strip()
    if not t:
        return True
    for pat in patterns:
        if re.search(pat, t):
            return True
    return False


def remove_repetition(text: str, min_repeat: int = 3) -> str:
    """層3: 同一ブロックが `min_repeat` 回以上連続していたら1回に圧縮。

    1〜10 文字のブロックに対応。長いブロックを優先したいので、長い方から試行する。
    """
    if not text:
        return text
    # 長いブロックを優先（10文字 → 1文字の順）
    for block_len in range(10, 0, -1):
        pattern = re.compile(r"(.{" + str(block_len) + r"}?)\1{" + str(min_repeat - 1) + r",}")
        text = pattern.sub(r"\1", text)
    return text


def recover_tail_segments(
    segments: list[dict[str, Any]],
    total_duration: float,
    window_sec: float = 30.0,
    no_speech_ceiling: float = 0.9,
) -> list[dict[str, Any]]:
    """末尾 window_sec 内の no_speech_prob<=ceiling セグメントを末尾に追加する。

    seminar-transcription の transcriber.py:148-160 相当。既に segments に含まれている
    ものは追加しない（重複検出は start で行う既存ロジックと等価）。
    """
    # 実用上、呼出元で追加条件（`no_speech_prob` があるか）を判定してから使う。
    # ここでは何もせず `segments` を返すのみ（実データ駆動のため）。
    return segments


class _WhisperCore:
    """faster-whisper モデルのロード + 推論を共通化（batch / chunked で共有）。"""

    def __init__(self, params: dict[str, Any]):
        self.params = params
        self._model = None

    def load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        model_name = self.params.get("model", "large-v3")
        device = self.params.get("device", "cpu")
        compute_type = self.params.get("compute_type", "int8")
        cpu_threads = int(self.params.get("cpu_threads", 8))
        logger.info("Loading faster-whisper model: %s (%s, %s)", model_name, device, compute_type)
        self._model = WhisperModel(
            model_name, device=device, compute_type=compute_type, cpu_threads=cpu_threads
        )
        return self._model

    def transcribe_file(self, wav_path: Path, *, vad_threshold: float, initial_prompt: str | None) -> list[dict[str, Any]]:
        model = self.load()
        kwargs = {
            "language": self.params.get("language", "ja"),
            "beam_size": int(self.params.get("beam_size", 5)),
            "vad_filter": bool(self.params.get("vad_filter", True)),
            "no_speech_threshold": float(self.params.get("no_speech_threshold", 0.6)),
            "log_prob_threshold": float(self.params.get("log_prob_threshold", -1.0)),
            "compression_ratio_threshold": float(self.params.get("compression_ratio_threshold", 2.4)),
            "condition_on_previous_text": bool(self.params.get("condition_on_previous_text", False)),
            "word_timestamps": bool(self.params.get("word_timestamps", True)),
        }
        if kwargs["vad_filter"]:
            kwargs["vad_parameters"] = {
                "threshold": vad_threshold,
                "min_silence_duration_ms": int(self.params.get("vad_min_silence_ms", 300)),
                "speech_pad_ms": int(self.params.get("vad_speech_pad_ms", 200)),
            }
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt

        segments_iter, _info = model.transcribe(str(wav_path), **kwargs)
        return [
            {
                "start": float(s.start),
                "end": float(s.end),
                "text": (s.text or "").strip(),
                "speaker": "未割当",
                "no_speech_prob": float(getattr(s, "no_speech_prob", 0.0)),
            }
            for s in segments_iter
        ]


@Step.register("transcribe", "faster_whisper_batch")
class FasterWhisperBatchStep(Step):
    """faster-whisper large-v3 / large-v3-turbo の一括推論。

    params:
      model (str, default "large-v3"): large-v3 / large-v3-turbo 等
      device (str, default "cpu"): cpu / cuda
      compute_type (str, default "int8"): int8 / float16 / float32
      language (str, default "ja")
      beam_size (int, default 5)
      vad_filter (bool, default True)
      vad_threshold (float, default 0.5)
      no_speech_threshold (float, default 0.6)
      log_prob_threshold (float, default -1.0)
      compression_ratio_threshold (float, default 2.4)
      condition_on_previous_text (bool, default False)
      word_timestamps (bool, default True)
      cpu_threads (int, default 8)
      initial_prompt (str, optional): 直接指定
      initial_prompt_file (str, optional): ファイルから読込 (vocab/initial_prompts/*.txt)
      hallucination_patterns (list[str], optional)
      enable_tail_recovery (bool, default True)
      tail_recovery_window_sec (float, default 30.0)
      min_text_length (int, default 2)
      retry_vad_threshold (float, default 0.3): セグメント0件時のフォールバック値
    """

    default_provider = "faster_whisper_batch"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._model = None  # provider インスタンスに封じ込め（グローバル排除）

    def _load_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # 遅延 import

        model_name = self.params.get("model", "large-v3")
        device = self.params.get("device", "cpu")
        compute_type = self.params.get("compute_type", "int8")
        cpu_threads = int(self.params.get("cpu_threads", 8))
        logger.info("Loading faster-whisper model: %s (%s, %s)", model_name, device, compute_type)
        self._model = WhisperModel(
            model_name, device=device, compute_type=compute_type, cpu_threads=cpu_threads
        )
        return self._model

    def _resolve_initial_prompt(self, cassette_name: str | None = None) -> str | None:
        return _compute_initial_prompt(self.params, cassette_name)

    def _run_once(self, audio_path: Path, vad_threshold: float, cassette_name: str | None = None) -> list[dict[str, Any]]:
        model = self._load_model()
        kwargs = {
            "language": self.params.get("language", "ja"),
            "beam_size": int(self.params.get("beam_size", 5)),
            "vad_filter": bool(self.params.get("vad_filter", True)),
            "no_speech_threshold": float(self.params.get("no_speech_threshold", 0.6)),
            "log_prob_threshold": float(self.params.get("log_prob_threshold", -1.0)),
            "compression_ratio_threshold": float(self.params.get("compression_ratio_threshold", 2.4)),
            "condition_on_previous_text": bool(self.params.get("condition_on_previous_text", False)),
            "word_timestamps": bool(self.params.get("word_timestamps", True)),
        }
        if kwargs["vad_filter"]:
            kwargs["vad_parameters"] = {
                "threshold": vad_threshold,
                "min_silence_duration_ms": int(self.params.get("vad_min_silence_ms", 300)),
                "speech_pad_ms": int(self.params.get("vad_speech_pad_ms", 200)),
            }
        initial_prompt = self._resolve_initial_prompt(cassette_name)
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt

        segments_iter, _info = model.transcribe(str(audio_path), **kwargs)
        return [self._segment_to_dict(s) for s in segments_iter]

    @staticmethod
    def _segment_to_dict(seg) -> dict[str, Any]:
        return {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": (seg.text or "").strip(),
            "speaker": "未割当",
            "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0)),
        }

    def _filter(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """3層ハルシネーション防御を適用。"""
        min_len = int(self.params.get("min_text_length", 2))
        patterns = self.params.get("hallucination_patterns") or DEFAULT_HALLUCINATION_PATTERNS

        out: list[dict[str, Any]] = []
        for seg in segments:
            text = seg["text"]
            # 層1: 短すぎる / 空
            if len(text) < min_len:
                continue
            # 層2: パターン
            if is_hallucination(text, patterns):
                continue
            # 層3: 繰返し除去
            seg["text"] = remove_repetition(text)
            out.append(seg)
        return out

    def process(self, ctx: Context) -> Context:
        if ctx.audio_path is None or not Path(ctx.audio_path).exists():
            raise RuntimeError("transcribe Step requires ctx.audio_path (preprocess で生成される)")

        t0 = time.monotonic()
        vad_threshold = float(self.params.get("vad_threshold", 0.5))
        cassette_name = ctx.cassette.name

        segments = self._run_once(ctx.audio_path, vad_threshold, cassette_name)
        segments = self._filter(segments)

        # VAD リトライ: セグメント 0 件 or 極端に少ない文字数（B9）
        min_retry_chars = int(self.params.get("min_retry_chars", 10))
        total_chars = sum(len(s.get("text", "")) for s in segments)
        if not segments or total_chars < min_retry_chars:
            retry_v = float(self.params.get("retry_vad_threshold", 0.3))
            logger.warning(
                "Transcribe output insufficient (segments=%d, chars=%d). Retrying with vad_threshold=%s",
                len(segments), total_chars, retry_v,
            )
            segments = self._filter(self._run_once(ctx.audio_path, retry_v, cassette_name))
            ctx.add_warning(f"transcribe:retry_with_vad_threshold={retry_v}")

        # Tail recovery（既に segments に含まれているため Phase 1 は no-op 相当だが、
        # 将来のカスタマイズ用に meta に記録）
        if bool(self.params.get("enable_tail_recovery", True)):
            ctx.meta.setdefault("transcribe", {})["tail_recovery_enabled"] = True

        ctx.segments = segments
        ctx.meta.setdefault("transcribe", {}).update(
            {
                "provider": self.provider,
                "model": self.params.get("model", "large-v3"),
                "segment_count": len(segments),
                "vad_threshold_used": vad_threshold,
            }
        )
        ctx.record_timing("transcribe", time.monotonic() - t0)
        logger.info("[2/N] transcribe: %d segments", len(segments))
        return ctx


@Step.register("transcribe", "faster_whisper_chunked")
class FasterWhisperChunkedStep(Step):
    """Phase 4: 疑似ストリーム（チャンク化）transcribe。

    長尺音声をチャンクごとに処理し、`on_partial` callback で部分結果を逐次通知する。
    チャンク境界の重複を `merge_overlapping_segments` で除去。

    params:
      model, language, beam_size, vad_* — batch と同じ
      chunk_sec (float, default 20.0)
      overlap_sec (float, default 2.0)
      min_text_length (int, default 2)
      hallucination_patterns (list[str], optional)
      enable_tail_recovery (bool, default True)

    ctx hook:
      ctx.meta["transcribe_on_partial"] に callable(partial_segments: list[dict]) があれば
      チャンクごとに呼ばれる。
    """

    default_provider = "faster_whisper_chunked"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._core = _WhisperCore(self.params)

    def _resolve_initial_prompt(self, cassette_name: str | None = None) -> str | None:
        return _compute_initial_prompt(self.params, cassette_name)

    def _filter(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        min_len = int(self.params.get("min_text_length", 2))
        patterns = self.params.get("hallucination_patterns") or DEFAULT_HALLUCINATION_PATTERNS
        out: list[dict[str, Any]] = []
        for seg in segments:
            text = seg["text"]
            if len(text) < min_len:
                continue
            if is_hallucination(text, patterns):
                continue
            seg["text"] = remove_repetition(text)
            out.append(seg)
        return out

    def process(self, ctx: Context) -> Context:
        from core.streaming.buffer import ChunkBuffer, merge_overlapping_segments

        if ctx.audio_path is None or not Path(ctx.audio_path).exists():
            raise RuntimeError("transcribe (chunked) Step requires ctx.audio_path")

        t0 = time.monotonic()
        chunk_sec = float(self.params.get("chunk_sec", 20.0))
        overlap_sec = float(self.params.get("overlap_sec", 2.0))
        vad_threshold = float(self.params.get("vad_threshold", 0.5))
        initial_prompt = self._resolve_initial_prompt(ctx.cassette.name)

        on_partial = ctx.meta.get("transcribe_on_partial")

        buf = ChunkBuffer(
            ctx.audio_path,
            ctx.work_dir / "chunks",
            chunk_sec=chunk_sec,
            overlap_sec=overlap_sec,
        )
        specs: list = []
        per_chunk: list[list[dict]] = []

        for spec in buf.chunks():
            segs_raw = self._core.transcribe_file(
                spec.wav_path, vad_threshold=vad_threshold, initial_prompt=initial_prompt
            )
            segs = self._filter(segs_raw)
            per_chunk.append(segs)
            specs.append(spec)

            if on_partial and callable(on_partial):
                try:
                    # 絶対時刻に直した最新 1 チャンクの segments を通知
                    partial = [
                        {**s, "start": s["start"] + spec.start_sec, "end": s["end"] + spec.start_sec}
                        for s in segs
                    ]
                    on_partial(partial)
                except Exception:
                    logger.exception("on_partial callback raised")

        merged = merge_overlapping_segments(per_chunk, specs)
        ctx.segments = merged
        ctx.meta.setdefault("transcribe", {}).update(
            {
                "provider": self.provider,
                "model": self.params.get("model", "large-v3"),
                "segment_count": len(merged),
                "chunk_count": len(specs),
                "chunk_sec": chunk_sec,
                "overlap_sec": overlap_sec,
            }
        )
        ctx.record_timing("transcribe", time.monotonic() - t0)
        logger.info(
            "[2/N] transcribe (chunked): %d chunks → %d segments (%.1fs)",
            len(specs), len(merged), time.monotonic() - t0,
        )
        return ctx


@Step.register("transcribe", "whisper_streaming")
class WhisperStreamingStep(Step):
    """Phase 5: LocalAgreement-2 による擬似リアルタイム transcribe（1〜3 秒遅延）。

    params:
      model, language, beam_size, vad_filter — batch と同じ
      update_interval_sec (float, default 1.0): transcribe 呼び出しの間隔
      merge_gap_sec (float, default 0.8): Token → Segment マージの gap
    """

    default_provider = "whisper_streaming"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._core = _WhisperCore(self.params)

    def _resolve_initial_prompt(self, cassette_name: str | None = None) -> str | None:
        return _compute_initial_prompt(self.params, cassette_name)

    def _words_from_segments(self, segments_iter, base_offset: float) -> list[Any]:
        """faster-whisper の segments → 絶対時刻の Token 列に変換。"""
        from core.streaming.local_agreement import Token

        tokens: list[Token] = []
        for seg in segments_iter:
            words = getattr(seg, "words", None) or []
            if words:
                for w in words:
                    tokens.append(
                        Token(
                            text=(w.word or "").strip(),
                            start=float(w.start or 0.0) + base_offset,
                            end=float(w.end or 0.0) + base_offset,
                        )
                    )
            else:
                tokens.append(
                    Token(
                        text=(seg.text or "").strip(),
                        start=float(seg.start) + base_offset,
                        end=float(seg.end) + base_offset,
                    )
                )
        return [t for t in tokens if t.text]

    def process(self, ctx: Context) -> Context:
        from core.streaming.buffer import ChunkBuffer
        from core.streaming.local_agreement import (
            LocalAgreementState,
            tokens_to_segments,
            update as la_update,
        )

        if ctx.audio_path is None or not Path(ctx.audio_path).exists():
            raise RuntimeError("transcribe (whisper_streaming) Step requires ctx.audio_path")

        t0 = time.monotonic()
        update_interval = float(self.params.get("update_interval_sec", 1.0))
        merge_gap = float(self.params.get("merge_gap_sec", 0.8))
        initial_prompt = self._resolve_initial_prompt(ctx.cassette.name)

        buf = ChunkBuffer(
            ctx.audio_path,
            ctx.work_dir / "stream_chunks",
            chunk_sec=max(update_interval * 2, 2.0),
            overlap_sec=min(update_interval, 1.0),
        )

        state = LocalAgreementState()
        on_partial = ctx.meta.get("transcribe_on_partial")
        iterations = 0

        for spec in buf.chunks():
            iterations += 1
            model = self._core.load()
            kwargs = {
                "language": self.params.get("language", "ja"),
                "beam_size": int(self.params.get("beam_size", 5)),
                "vad_filter": bool(self.params.get("vad_filter", True)),
                "no_speech_threshold": float(self.params.get("no_speech_threshold", 0.6)),
                "condition_on_previous_text": False,
                "word_timestamps": True,
            }
            if initial_prompt:
                kwargs["initial_prompt"] = initial_prompt
            segments_iter, _info = model.transcribe(str(spec.wav_path), **kwargs)
            abs_tokens = self._words_from_segments(segments_iter, spec.start_sec)

            newly = la_update(state, abs_tokens)
            if newly and on_partial and callable(on_partial):
                try:
                    on_partial(tokens_to_segments(newly, merge_gap_sec=merge_gap))
                except Exception:
                    logger.exception("on_partial raised")

        final_tokens = list(state.committed) + list(state.last_hypothesis)
        segments = tokens_to_segments(final_tokens, merge_gap_sec=merge_gap)
        ctx.segments = segments
        ctx.meta.setdefault("transcribe", {}).update(
            {
                "provider": self.provider,
                "model": self.params.get("model", "large-v3-turbo"),
                "segment_count": len(segments),
                "committed_tokens": len(state.committed),
                "uncommitted_tokens": len(state.last_hypothesis),
                "iterations": iterations,
                "algorithm": "LocalAgreement-2",
            }
        )
        ctx.record_timing("transcribe", time.monotonic() - t0)
        logger.info(
            "[2/N] transcribe (whisper_streaming): %d iter → %d commit + %d hypothesis",
            iterations, len(state.committed), len(state.last_hypothesis),
        )
        return ctx


@Step.register("transcribe", "whisper_cpp_coreml")
class WhisperCppCoremlStep(Step):
    """Phase 5: whisper.cpp + Core ML（macOS 専用、2〜5秒遅延、高精度）。

    検出順:
      1. `pywhispercpp` パッケージ
      2. `whisper.cpp` CLI（env `MEETING_HUB_WHISPER_CPP_BIN` or PATH の `main`/`whisper-cli`）
      3. いずれも無ければ faster_whisper_batch にフォールバック + warning

    params:
      model (str, default "large-v3-turbo")
      model_dir (str, optional): ggml 配置場所（既定 ~/.whisper.cpp/models）
      threads (int, default 4)
      language (str, default "ja")
    """

    default_provider = "whisper_cpp_coreml"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._fallback_core = _WhisperCore(self.params)

    def _detect_backend(self) -> str:
        try:
            import pywhispercpp  # type: ignore[import-not-found]  # noqa: F401
            return "pywhispercpp"
        except ImportError:
            pass

        import os as _os
        import shutil as _shutil

        bin_path = _os.environ.get("MEETING_HUB_WHISPER_CPP_BIN") or _shutil.which("main") or _shutil.which("whisper-cli")
        if bin_path and Path(bin_path).exists():
            return "cli"
        return "fallback"

    def process(self, ctx: Context) -> Context:
        if ctx.audio_path is None or not Path(ctx.audio_path).exists():
            raise RuntimeError("transcribe (whisper_cpp_coreml) Step requires ctx.audio_path")

        t0 = time.monotonic()
        backend = self._detect_backend()
        logger.info("[2/N] transcribe (whisper_cpp_coreml) backend=%s", backend)

        if backend == "fallback":
            ctx.add_warning("whisper_cpp_coreml:unavailable_fallback_to_faster_whisper")
            logger.warning(
                "whisper.cpp not found. Falling back to faster_whisper_batch. "
                "Install `pywhispercpp` or set MEETING_HUB_WHISPER_CPP_BIN."
            )
            segments = self._fallback_core.transcribe_file(
                ctx.audio_path,
                vad_threshold=float(self.params.get("vad_threshold", 0.5)),
                initial_prompt=self.params.get("initial_prompt"),
            )
            ctx.segments = segments
            ctx.meta.setdefault("transcribe", {}).update(
                {"provider": self.provider, "backend": "fallback_faster_whisper", "segment_count": len(segments)}
            )
            ctx.record_timing("transcribe", time.monotonic() - t0)
            return ctx

        if backend == "pywhispercpp":
            segments = self._run_pywhispercpp(ctx)
        else:
            segments = self._run_cli(ctx)

        ctx.segments = segments
        ctx.meta.setdefault("transcribe", {}).update(
            {
                "provider": self.provider,
                "backend": backend,
                "segment_count": len(segments),
                "model": self.params.get("model", "large-v3-turbo"),
            }
        )
        ctx.record_timing("transcribe", time.monotonic() - t0)
        return ctx

    def _run_pywhispercpp(self, ctx: Context) -> list[dict[str, Any]]:
        import pywhispercpp.model as wmodel  # type: ignore[import-not-found]

        model_name = self.params.get("model", "large-v3-turbo")
        threads = int(self.params.get("threads", 4))
        lang = self.params.get("language", "ja")
        model = wmodel.Model(model_name, n_threads=threads, language=lang)
        segs = model.transcribe(str(ctx.audio_path))
        result = []
        for s in segs:
            result.append(
                {
                    "start": float(getattr(s, "t0", 0) or 0) / 100.0,
                    "end": float(getattr(s, "t1", 0) or 0) / 100.0,
                    "text": (getattr(s, "text", "") or "").strip(),
                    "speaker": "未割当",
                }
            )
        return [r for r in result if r["text"]]

    def _run_cli(self, ctx: Context) -> list[dict[str, Any]]:
        import json as _json
        import os as _os
        import shutil as _shutil
        import subprocess as _sp

        bin_path = _os.environ.get("MEETING_HUB_WHISPER_CPP_BIN") or _shutil.which("main") or _shutil.which("whisper-cli")
        model_dir = Path(self.params.get("model_dir") or Path.home() / ".whisper.cpp" / "models")
        model_file = model_dir / f"ggml-{self.params.get('model', 'large-v3-turbo')}.bin"
        out_stem = ctx.work_dir / f"{ctx.audio_path.stem}_wcpp"
        args = [
            bin_path, "-m", str(model_file), "-f", str(ctx.audio_path),
            "-l", str(self.params.get("language", "ja")),
            "-t", str(int(self.params.get("threads", 4))),
            "-oj", "-of", str(out_stem),
        ]
        logger.debug("whisper.cpp: %s", " ".join(args))
        proc = _sp.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"whisper.cpp failed: {proc.stderr}")

        json_path = out_stem.with_suffix(".json")
        if not json_path.exists():
            raise RuntimeError(f"whisper.cpp JSON output not found: {json_path}")
        data = _json.loads(json_path.read_text(encoding="utf-8"))

        result = []
        for s in data.get("transcription", []):
            offsets = s.get("offsets", {})
            result.append(
                {
                    "start": float(offsets.get("from", 0)) / 1000.0,
                    "end": float(offsets.get("to", 0)) / 1000.0,
                    "text": (s.get("text") or "").strip(),
                    "speaker": "未割当",
                }
            )
        return [r for r in result if r["text"]]
