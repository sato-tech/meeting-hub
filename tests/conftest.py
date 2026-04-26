"""共通 fixture。"""
from __future__ import annotations

import sys
from pathlib import Path

# リポジトリルートを sys.path に追加（from core.xxx import ... を許可）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core.cassette_schema import (  # noqa: E402
    CassetteConfig,
    InputConfig,
    LocalDestination,
    OutputConfig,
    StepConfig,
)


@pytest.fixture
def minimal_cassette() -> CassetteConfig:
    """最小構成のカセット。`cloud_batch` モード、全 Step enabled。"""
    return CassetteConfig(
        name="test",
        description="pytest minimal",
        mode="cloud_batch",
        input=InputConfig(type="file", storage="local"),
        pipeline=[
            StepConfig(step="preprocess", provider="default", params={"target_sr": 16000}),
            StepConfig(step="transcribe", provider="faster_whisper_batch", params={"model": "tiny"}),
            StepConfig(step="diarize", provider="pyannote", enabled=False, params={}),
            StepConfig(step="term_correct", provider="regex", params={}),
            StepConfig(step="llm_cleanup", provider="claude", enabled=False, params={}),
            StepConfig(step="minutes_extract", provider="claude", enabled=False, params={}),
            StepConfig(step="format", params={}),
        ],
        output=OutputConfig(formats=["md"], destinations=[LocalDestination(path="./output/test/")]),
    )


@pytest.fixture
def tmp_work_dir(tmp_path: Path) -> Path:
    d = tmp_path / "work"
    d.mkdir()
    return d
