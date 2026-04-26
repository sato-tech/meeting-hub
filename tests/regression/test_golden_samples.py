"""Golden sample 回帰テスト骨子（REPORT_PROMPT_B.md §8.3 / REPORT_PROMPT_C.md §6）。

実 API / 実モデルは叩かない（§12-9）。golden_samples/ に sources と metrics.json が
揃っている場合のみ実行される。CI ではスキップ前提（pytest -m "not regression"）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

GOLDEN_ROOT = Path(
    os.environ.get(
        "GOLDEN_SAMPLES_ROOT",
        str(Path(__file__).resolve().parents[2] / "golden_samples"),
    )
)

SAMPLES = [
    ("S01/01", "sales_meeting"),
    ("S01/02", "sales_meeting"),
    ("S02/01", "internal_meeting"),
    ("S02/02", "internal_meeting"),
    ("S03/01", "seminar"),
    ("S03/02", "seminar"),
]

TOLERANCES = {
    "segment_count": 0.05,        # ±5%
    "total_chars": 0.03,          # ±3%
    "term_correct_applied": 1,    # ±1 件（絶対値）
}


pytestmark = pytest.mark.regression


@pytest.mark.parametrize("sample_id,cassette_name", SAMPLES)
def test_new_pipeline_matches_golden(sample_id: str, cassette_name: str, tmp_path) -> None:
    sample_dir = GOLDEN_ROOT / sample_id
    if not (sample_dir / "metrics.json").exists():
        pytest.skip(f"golden metrics not present: {sample_dir}")
    src = sample_dir / "source.mp4"
    if not src.exists():
        pytest.skip(f"source audio not present: {src}")

    # 実際の Pipeline 実行は実モデル・実 API が必要なため、このテストは
    # `GOLDEN_SAMPLES_ROOT` を明示設定した上で手動実行を想定。
    # ここでは metrics.json の読み込みだけ検証（フィクスチャの破損検知）。
    from core.metrics import metrics_from_golden_dir

    golden = metrics_from_golden_dir(sample_dir)
    assert "segment_count" in golden
    assert "total_chars" in golden
