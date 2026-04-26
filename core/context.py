"""Context — Step 間で共有される実行状態。

設計意図（REPORT_PROMPT_B.md §2）:
  - 既存2リポの `config.NUM_SPEAKERS = ...` 等のグローバル書き換えを排除
  - Step 間受渡を明示化
  - Phase 2 以降の streaming フラグも予約済（Phase 1 は常に False）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.cassette_schema import CassetteConfig, StepName


@dataclass
class Context:
    """パイプライン全体で共有する実行状態。"""

    input_path: Path
    cassette: CassetteConfig

    audio_path: Path | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    cleaned_text: str | None = None
    minutes: dict[str, Any] | None = None
    outputs: dict[str, Path] = field(default_factory=dict)

    run_id: str = ""
    work_dir: Path = field(default_factory=lambda: Path("."))
    streaming: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def step_params(self, step: StepName) -> dict[str, Any]:
        sc = self.cassette.get_step(step)
        return sc.params if sc else {}

    def add_warning(self, message: str) -> None:
        self.meta.setdefault("warnings", []).append(message)

    def record_timing(self, step: StepName, seconds: float) -> None:
        self.meta.setdefault("timings", {})[step] = seconds
