"""Pipeline オーケストレータ。

Phase 2 追加機能:
  - `--resume <run_id>` 対応（Step 単位の checkpoint ロード）
  - `streaming` モード（live_audio 入力で preprocess スキップ）
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.adapters.base import InputAdapter
from core.cassette_schema import CassetteConfig
from core.context import Context
from core.runtime import get_runtime  # noqa: F401 — 登録 side-effect
from core.steps.base import Step
import core.destinations  # noqa: F401  — Destination レジストリ登録
import core.runtime  # noqa: F401  — Runtime レジストリ登録
import core.steps  # noqa: F401  — Step レジストリ登録

logger = logging.getLogger(__name__)


_CHECKPOINT_DIR_NAME = "checkpoints"


def _make_run_id(stem: str) -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{stem}"


def _save_checkpoint(ctx: Context, step_name: str) -> None:
    try:
        cp_dir = ctx.work_dir / _CHECKPOINT_DIR_NAME
        cp_dir.mkdir(parents=True, exist_ok=True)

        # Step が成果物を work_dir に出してくれている前提で、resume 用のデータ参照先を保存
        payload: dict[str, Any] = {
            "step": step_name,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "segments_count": len(ctx.segments),
            "has_cleaned_text": ctx.cleaned_text is not None,
            "has_minutes": ctx.minutes is not None,
            "audio_path": str(ctx.audio_path) if ctx.audio_path else None,
            "outputs": {k: str(v) for k, v in ctx.outputs.items()},
            "meta": ctx.meta,
        }

        # 実データもダンプ（resume 時にこれを読み戻す）
        if ctx.segments:
            (cp_dir / f"{step_name}_segments.json").write_text(
                json.dumps(ctx.segments, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if ctx.cleaned_text is not None:
            (cp_dir / f"{step_name}_cleaned.txt").write_text(ctx.cleaned_text, encoding="utf-8")
        if ctx.minutes is not None:
            (cp_dir / f"{step_name}_minutes.json").write_text(
                json.dumps(ctx.minutes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        (cp_dir / f"{step_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("checkpoint save failed for %s: %s", step_name, e)


def _find_run_dir(output_root: Path, run_id: str) -> Path:
    candidate = output_root / run_id
    if candidate.exists():
        return candidate
    # 部分一致（stem だけ指定された場合）
    matches = sorted(output_root.glob(f"*{run_id}*"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"Cannot resolve run directory for run_id={run_id!r}")


def _load_latest_checkpoint(work_dir: Path, step_order: list[str]) -> tuple[str | None, dict]:
    """完了済みの最後の step 名と payload を返す。存在しなければ (None, {})。"""
    cp_dir = work_dir / _CHECKPOINT_DIR_NAME
    if not cp_dir.exists():
        return None, {}
    last_step: str | None = None
    last_payload: dict = {}
    for s in step_order:
        p = cp_dir / f"{s}.json"
        if p.exists():
            last_step = s
            last_payload = json.loads(p.read_text(encoding="utf-8"))
    return last_step, last_payload


def _restore_context(ctx: Context, last_step: str) -> Context:
    """最後に完了した Step の中間データを ctx に詰め直す。"""
    cp_dir = ctx.work_dir / _CHECKPOINT_DIR_NAME
    payload_path = cp_dir / f"{last_step}.json"
    if not payload_path.exists():
        return ctx
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    if payload.get("audio_path"):
        ctx.audio_path = Path(payload["audio_path"])

    # 最新の segments / cleaned / minutes を再構築
    seg_file = cp_dir / f"{last_step}_segments.json"
    if seg_file.exists():
        ctx.segments = json.loads(seg_file.read_text(encoding="utf-8"))

    clean_file = cp_dir / f"{last_step}_cleaned.txt"
    if clean_file.exists():
        ctx.cleaned_text = clean_file.read_text(encoding="utf-8")

    min_file = cp_dir / f"{last_step}_minutes.json"
    if min_file.exists():
        ctx.minutes = json.loads(min_file.read_text(encoding="utf-8"))

    ctx.meta.update(payload.get("meta") or {})
    ctx.meta["resumed_from"] = last_step
    return ctx


class Pipeline:
    def __init__(self, cassette: CassetteConfig, adapter: InputAdapter):
        self.cassette = cassette
        self.adapter = adapter
        self.step_cfgs = [sc for sc in cassette.pipeline if sc.enabled]
        self.steps = [Step.create(sc) for sc in self.step_cfgs]
        # Step と runtime 指定のペア（StepConfig.runtime に従う）
        self.runtimes = [sc.runtime for sc in self.step_cfgs]
        # 進捗コールバック（M16 で使用）
        self.on_step_start = None  # callable(step_name) -> None
        self.on_step_complete = None  # callable(step_name, elapsed_sec) -> None

    def run(
        self,
        input_uri: str,
        output_root: Path,
        *,
        strict_destinations: bool = False,
        resume_run_id: str | None = None,
    ) -> Context:
        from core.hooks import log_summary, run_pre_hooks

        if resume_run_id:
            return self._run_resume(resume_run_id, output_root, strict_destinations)

        local_path = self.adapter.acquire(input_uri)
        run_id = _make_run_id(local_path.stem)
        work_dir = output_root / run_id
        work_dir.mkdir(parents=True, exist_ok=True)

        streaming = self.cassette.input.type != "file"
        ctx = Context(
            input_path=local_path,
            cassette=self.cassette,
            work_dir=work_dir,
            run_id=run_id,
            streaming=streaming,
        )

        run_pre_hooks(ctx)
        self._execute_steps(ctx, skip_up_to=None)
        log_summary(ctx)
        self._run_destinations(ctx, strict=strict_destinations)
        self.adapter.cleanup()
        return ctx

    def _run_resume(self, resume_run_id: str, output_root: Path, strict: bool) -> Context:
        from core.hooks import log_summary

        work_dir = _find_run_dir(output_root, resume_run_id)
        step_order = [s.name for s in self.steps]
        last_step, payload = _load_latest_checkpoint(work_dir, step_order)
        if last_step is None:
            raise RuntimeError(
                f"No checkpoint found under {work_dir}. Cannot resume. "
                "Run without --resume to start fresh."
            )
        logger.info("Resuming from step=%s (run_id=%s)", last_step, work_dir.name)

        # input_path は checkpoint に保存していないので work_dir 情報から推定
        # audio_path が保存されていればそれを使い、input_path はダミーに設定
        audio_path = payload.get("audio_path")
        input_path = Path(audio_path) if audio_path else work_dir

        ctx = Context(
            input_path=input_path,
            cassette=self.cassette,
            work_dir=work_dir,
            run_id=work_dir.name,
            streaming=self.cassette.input.type != "file",
        )
        _restore_context(ctx, last_step)

        self._execute_steps(ctx, skip_up_to=last_step)
        log_summary(ctx)
        self._run_destinations(ctx, strict=strict)
        return ctx

    def _execute_steps(self, ctx: Context, *, skip_up_to: str | None) -> None:
        """skip_up_to が指定されればその Step まで skip、以降のみ実行。"""
        from core.runtime import get_runtime

        skipping = skip_up_to is not None
        total = len(self.steps)
        for i, (step, runtime_name) in enumerate(zip(self.steps, self.runtimes), 1):
            if skipping:
                if step.name == skip_up_to:
                    skipping = False
                    logger.info("[%d/%d] %s (resumed, skipping)", i, total, step.name)
                else:
                    logger.info("[%d/%d] %s (skipped by resume)", i, total, step.name)
                continue

            logger.info("[%d/%d] %s (provider=%s, runtime=%s)", i, total, step.name, step.provider, runtime_name)
            if self.on_step_start:
                try:
                    self.on_step_start(step.name)
                except Exception:
                    pass
            t0 = time.monotonic()
            try:
                runtime = get_runtime(runtime_name)
                ctx = runtime.execute(step, ctx)
            except Exception as e:
                step.on_error(ctx, e)
                logger.exception("Step %s failed", step.name)
                raise
            elapsed = time.monotonic() - t0
            _save_checkpoint(ctx, step.name)
            ctx.record_timing(step.name, elapsed)
            if self.on_step_complete:
                try:
                    self.on_step_complete(step.name, elapsed)
                except Exception:
                    pass

    def _run_destinations(self, ctx: Context, *, strict: bool) -> None:
        from core.destinations import Destination

        for dest_cfg in ctx.cassette.output.destinations:
            impl = Destination.create(dest_cfg)
            try:
                impl.send(ctx)
            except NotImplementedError as e:
                msg = f"destination:{dest_cfg.type}:not-implemented"
                ctx.add_warning(msg)
                logger.warning("[skeleton] %s (%s)", msg, e)
                if strict:
                    raise
            except Exception as e:
                ctx.add_warning(f"destination:{dest_cfg.type}:error:{e}")
                logger.exception("destination %s failed", dest_cfg.type)
                if strict:
                    raise
