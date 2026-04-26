"""全カセットがスキーマ違反なくロードできることの統合テスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.cassette import load_cassette

_CASSETTES = [
    "sales_meeting",
    "internal_meeting",
    "seminar",
    "one_on_one",
    "interview",
]

# 旧 live_* カセット名（deprecation マッピングで同 cassette + live=True に流される）
_DEPRECATED_LIVE_NAMES = ["live_sales", "live_internal", "one_on_one_live"]


@pytest.mark.parametrize("name", _CASSETTES)
def test_cassette_loads_and_validates(name: str) -> None:
    c = load_cassette(name)
    assert c.name
    assert c.pipeline
    # preprocess → ... → format までの並びを軽くチェック
    step_names = [s.step for s in c.pipeline]
    assert "preprocess" in step_names
    assert "transcribe" in step_names
    assert "format" in step_names


@pytest.mark.parametrize("name", _CASSETTES)
def test_cassette_loads_with_live_profile(name: str) -> None:
    """すべての canonical カセットで live=True が schema 妥当性を保つ。"""
    c = load_cassette(name, live=True)
    assert c.input.type == "live_audio"
    assert c.llm.batch_mode is False
    # transcribe は chunked に、diarize は channel_based に
    tr = c.get_step("transcribe")
    assert tr.provider == "faster_whisper_chunked"
    di = c.get_step("diarize")
    if di and di.enabled:
        assert di.provider == "channel_based"


@pytest.mark.parametrize("old,new", [
    ("live_sales", "sales_meeting"),
    ("live_internal", "internal_meeting"),
    ("one_on_one_live", "one_on_one"),
])
def test_deprecated_live_name_is_auto_mapped(old: str, new: str, caplog) -> None:
    c = load_cassette(old)
    assert c.name == new                    # 中身は canonical カセット
    assert c.input.type == "live_audio"      # live プロファイルが当たっている


def test_override_applies() -> None:
    c = load_cassette("sales_meeting", overrides=["transcribe.params.beam_size=3"])
    transcribe = c.get_step("transcribe")
    assert transcribe.params["beam_size"] == 3


def test_override_enables_disables() -> None:
    c = load_cassette("sales_meeting", overrides=["llm_cleanup.enabled=false"])
    assert c.get_step("llm_cleanup").enabled is False
