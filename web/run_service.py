"""Streamlit から呼ばれる Pipeline 実行ファサード。"""
from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Any

from core.adapters.file import FileAdapter
from core.adapters.live_audio import LiveAudioAdapter
from core.cassette import load_cassette
from core.context import Context
from core.history import JobHistory
from core.pipeline import Pipeline

logger = logging.getLogger(__name__)


class RunService:
    """ジョブ起動・履歴連携の薄いサービス層。"""

    def __init__(self, history: JobHistory, output_root: Path):
        self.history = history
        self.output_root = Path(output_root).expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

    def start_job(
        self,
        *,
        user_id: str,
        cassette_name: str,
        input_path: Path | str,
        overrides: list[str] | None = None,
        run_in_thread: bool = True,
    ) -> str:
        """ジョブを起動し job_id を返す。"""
        cassette = load_cassette(cassette_name, overrides=overrides or [])

        local_path = Path(input_path) if not str(input_path).startswith("live://") else None
        input_name = local_path.name if local_path else str(input_path)

        # 仮の run_id（Pipeline で最終確定だが history にも記録）
        from datetime import datetime
        stem = local_path.stem if local_path else "live"
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{stem}"
        work_dir = self.output_root / run_id

        job_id = self.history.create(
            run_id=run_id,
            user_id=user_id,
            cassette=cassette_name,
            input_name=input_name,
            work_dir=str(work_dir),
            meta={"overrides": overrides or []},
        )

        def _run() -> None:
            try:
                self.history.update_status(job_id, "running")
                if cassette.input.type == "live_audio":
                    adapter = LiveAudioAdapter(mix=cassette.input.mix or "separate")
                    uri = str(input_path) if str(input_path).startswith("live://") else "live://"
                else:
                    adapter = FileAdapter(storage=cassette.input.storage)
                    uri = str(input_path)

                pipe = Pipeline(cassette, adapter)
                pipe.on_step_start = lambda name: self.history.log_event(job_id, name, "start")
                pipe.on_step_complete = lambda name, elapsed: self.history.log_event(
                    job_id, name, "end", detail={"elapsed_sec": round(elapsed, 2)}
                )
                ctx = pipe.run(uri, self.output_root)
                self.history.update_status(
                    job_id,
                    "completed",
                    finished=True,
                    meta={
                        "overrides": overrides or [],
                        "outputs": {k: str(v) for k, v in ctx.outputs.items()},
                        "warnings": ctx.meta.get("warnings", []),
                        "timings": ctx.meta.get("timings", {}),
                    },
                )
                logger.info("[run_service] job %s completed", job_id)
            except Exception as e:
                logger.exception("[run_service] job %s failed", job_id)
                self.history.update_status(
                    job_id,
                    "failed",
                    finished=True,
                    meta={"error": str(e), "overrides": overrides or []},
                )

        if run_in_thread:
            t = threading.Thread(target=_run, daemon=True, name=f"job-{job_id}")
            t.start()
        else:
            _run()

        return job_id
