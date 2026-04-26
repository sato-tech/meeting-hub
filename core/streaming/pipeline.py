"""StreamingPipeline — 非同期（threading）の擬似ストリーム実行器。

Phase 4 設計:
  - 音声取り込み（live_audio の acquire）は完了後に WAV を返す擬似ストリーム
  - その WAV を ChunkBuffer で分解して順次 transcribe
  - `on_partial(segments_absolute)` callback でチャンク毎の結果を通知
  - 完了後は既存 Pipeline と同じく diarize → cleanup → format を通す

真リアルタイム（Phase 5, whisper_streaming LocalAgreement-2）では
`stream()` の Iterator[bytes] を直接チャンクキューに流し込む別クラスに分ける予定。
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from core.adapters.base import InputAdapter
from core.cassette_schema import CassetteConfig
from core.context import Context
from core.pipeline import Pipeline, _make_run_id
from core.steps.base import Step

logger = logging.getLogger(__name__)


class StreamingPipeline:
    """Phase 4 の擬似ストリームラッパ。

    内部で `Pipeline` を使うが、transcribe 直前に `ctx.meta["transcribe_on_partial"]` を
    設定しておき、chunked provider がチャンク毎に callback を呼ぶ。
    """

    def __init__(
        self,
        cassette: CassetteConfig,
        adapter: InputAdapter,
        *,
        on_partial: Callable[[list[dict]], None] | None = None,
        on_step_start: Callable[[str], None] | None = None,
        on_step_complete: Callable[[str, float], None] | None = None,
    ):
        self.cassette = cassette
        self.adapter = adapter
        self.on_partial = on_partial
        self.on_step_start = on_step_start
        self.on_step_complete = on_step_complete
        self._partial_queue: queue.Queue = queue.Queue()
        self._pipeline: Pipeline | None = None

    def run(self, input_uri: str, output_root: Path) -> Context:
        pipe = Pipeline(self.cassette, self.adapter)
        self._pipeline = pipe
        pipe.on_step_start = self.on_step_start
        pipe.on_step_complete = self.on_step_complete

        ctx = pipe.run(input_uri, output_root)  # type: ignore[return-value]
        return ctx

    # ── 非同期版 ────────────────────────────
    def run_async(self, input_uri: str, output_root: Path) -> "StreamingJob":
        """別スレッドで実行し、partial segments を push するハンドル。"""
        job = StreamingJob(self, input_uri, output_root)
        job.start()
        return job


class StreamingJob:
    """バックグラウンドスレッド + partial queue でストリーム結果を受け取るハンドル。"""

    def __init__(self, pipe: StreamingPipeline, input_uri: str, output_root: Path):
        self._pipe = pipe
        self._input_uri = input_uri
        self._output_root = output_root
        self._thread: threading.Thread | None = None
        self._q: queue.Queue = queue.Queue()
        self._ctx: Context | None = None
        self._error: Exception | None = None
        self._done = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            # partial を queue に push する callback に差し替え
            user_on_partial = self._pipe.on_partial

            def _push_partial(segs: list[dict]) -> None:
                self._q.put(("partial", segs))
                if user_on_partial:
                    try:
                        user_on_partial(segs)
                    except Exception:
                        logger.exception("user on_partial raised")

            # Pipeline を直接構築し、partial hook を ctx.meta に仕込む
            from core.pipeline import Pipeline
            pipe = Pipeline(self._pipe.cassette, self._pipe.adapter)
            pipe.on_step_start = self._pipe.on_step_start
            pipe.on_step_complete = self._pipe.on_step_complete
            self._pipe._pipeline = pipe

            # acquire → ctx 構築（Pipeline.run を再実装せず hook 経由で）
            local_path = pipe.adapter.acquire(self._input_uri)
            run_id = _make_run_id(local_path.stem)
            work_dir = self._output_root / run_id
            work_dir.mkdir(parents=True, exist_ok=True)

            ctx = Context(
                input_path=local_path,
                cassette=pipe.cassette,
                work_dir=work_dir,
                run_id=run_id,
                streaming=True,
            )
            ctx.meta["transcribe_on_partial"] = _push_partial

            from core.hooks import log_summary, run_pre_hooks
            run_pre_hooks(ctx)
            pipe._execute_steps(ctx, skip_up_to=None)
            log_summary(ctx)
            pipe._run_destinations(ctx, strict=False)
            pipe.adapter.cleanup()

            self._ctx = ctx
            self._q.put(("complete", ctx))
        except Exception as e:
            self._error = e
            self._q.put(("error", e))
        finally:
            self._done.set()

    def partial_events(self, timeout: float | None = None):
        """キューからイベントを yield する。('partial', segs) / ('complete', ctx) / ('error', exc)"""
        while True:
            try:
                kind, payload = self._q.get(timeout=timeout) if timeout else self._q.get()
            except queue.Empty:
                break
            yield kind, payload
            if kind in ("complete", "error"):
                return

    def wait(self, timeout: float | None = None) -> Context:
        self._done.wait(timeout=timeout)
        if self._error:
            raise self._error
        assert self._ctx is not None
        return self._ctx

    @property
    def done(self) -> bool:
        return self._done.is_set()
