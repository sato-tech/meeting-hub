"""transcribe Step のフィルタ純関数テスト（モデル非依存）。"""
from __future__ import annotations

from core.steps.transcribe import (
    DEFAULT_HALLUCINATION_PATTERNS,
    FasterWhisperBatchStep,
    is_hallucination,
    remove_repetition,
)


def test_is_hallucination_matches_known_patterns() -> None:
    assert is_hallucination("ご視聴ありがとうございました", DEFAULT_HALLUCINATION_PATTERNS)
    assert is_hallucination("チャンネル登録お願いします", DEFAULT_HALLUCINATION_PATTERNS)
    assert is_hallucination("いいねお願いします", DEFAULT_HALLUCINATION_PATTERNS)


def test_is_hallucination_passes_normal_text() -> None:
    assert not is_hallucination("本日の議題は来期の予算についてです", DEFAULT_HALLUCINATION_PATTERNS)
    assert not is_hallucination("こんにちは、よろしくお願いします", DEFAULT_HALLUCINATION_PATTERNS)


def test_is_hallucination_empty() -> None:
    assert is_hallucination("", DEFAULT_HALLUCINATION_PATTERNS)
    assert is_hallucination("   ", DEFAULT_HALLUCINATION_PATTERNS)


def test_remove_repetition_collapses_repeats() -> None:
    assert remove_repetition("あああああああ") == "あ"  # 2文字以下は min_repeat=3
    assert remove_repetition("abcabcabcabc") == "abc"
    # 2文字ブロック × 3回以上
    assert remove_repetition("よしよしよしよし") == "よし"


def test_remove_repetition_keeps_normal() -> None:
    assert remove_repetition("議事録の内容について確認します") == "議事録の内容について確認します"
    assert remove_repetition("") == ""


def test_filter_removes_short_and_hallucinations() -> None:
    step = FasterWhisperBatchStep(
        provider="faster_whisper_batch",
        params={"min_text_length": 2},
    )
    segs = [
        {"start": 0.0, "end": 1.0, "text": "あ", "speaker": "未割当"},  # 短すぎ
        {"start": 1.0, "end": 2.0, "text": "ご視聴ありがとうございました", "speaker": "未割当"},  # パターン
        {"start": 2.0, "end": 5.0, "text": "本日の議題について", "speaker": "未割当"},  # OK
    ]
    filtered = step._filter(segs)
    assert len(filtered) == 1
    assert filtered[0]["text"] == "本日の議題について"


def test_filter_applies_repetition_removal() -> None:
    step = FasterWhisperBatchStep(provider="faster_whisper_batch", params={})
    segs = [{"start": 0.0, "end": 3.0, "text": "はいはいはいはい", "speaker": "未割当"}]
    filtered = step._filter(segs)
    assert len(filtered) == 1
    assert filtered[0]["text"] == "はい"


def test_resolve_initial_prompt_from_file(tmp_path) -> None:
    p = tmp_path / "vocab.txt"
    p.write_text("SaaS MRR ARR KPI OKR PoC ROI", encoding="utf-8")
    step = FasterWhisperBatchStep(
        provider="faster_whisper_batch",
        params={"initial_prompt_file": str(p)},
    )
    got = step._resolve_initial_prompt()
    assert got is not None
    assert "SaaS" in got


def test_resolve_initial_prompt_combines_file_and_direct(tmp_path) -> None:
    p = tmp_path / "vocab.txt"
    p.write_text("SaaS MRR", encoding="utf-8")
    step = FasterWhisperBatchStep(
        provider="faster_whisper_batch",
        params={"initial_prompt_file": str(p), "initial_prompt": "Acme"},
    )
    got = step._resolve_initial_prompt()
    assert got == "SaaS MRR Acme"


def test_resolve_initial_prompt_none() -> None:
    step = FasterWhisperBatchStep(provider="faster_whisper_batch", params={})
    assert step._resolve_initial_prompt() is None
