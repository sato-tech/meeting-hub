"""llm_cleanup Step のチャンキングロジックテスト。"""
from __future__ import annotations

from core.steps.llm_cleanup import chunk_segments, format_chunk_as_text


def _seg(start: float, end: float, text: str, speaker: str = "A") -> dict:
    return {"start": start, "end": end, "text": text, "speaker": speaker}


def test_chunk_empty() -> None:
    assert chunk_segments([]) == []


def test_chunk_under_soft_keeps_one_chunk() -> None:
    segs = [_seg(0.0, 1.0, "a" * 100)]
    chunks = chunk_segments(segs, max_chars=1000, soft_chars=500, preferred_gap=2.0)
    assert len(chunks) == 1


def test_chunk_splits_on_gap_after_soft() -> None:
    segs = [
        _seg(0.0, 1.0, "a" * 600),       # >= soft
        _seg(5.0, 6.0, "b" * 100),        # gap = 4.0s > 2.0 → 分割
    ]
    chunks = chunk_segments(segs, max_chars=2000, soft_chars=500, preferred_gap=2.0)
    assert len(chunks) == 2


def test_chunk_splits_on_max_even_without_gap() -> None:
    segs = [
        _seg(0.0, 1.0, "a" * 900),
        _seg(1.1, 2.0, "b" * 900),
        _seg(2.1, 3.0, "c" * 900),
    ]
    chunks = chunk_segments(segs, max_chars=1500, soft_chars=1200, preferred_gap=5.0)
    assert len(chunks) >= 2
    for c in chunks:
        assert sum(len(s["text"]) for s in c) <= 1500


def test_format_includes_timestamps_and_speaker() -> None:
    segs = [_seg(65.0, 70.0, "hello", speaker="A")]
    text = format_chunk_as_text(segs)
    assert "[01:05]" in text
    assert "A: hello" in text


def test_format_skips_unassigned_speaker_prefix() -> None:
    segs = [_seg(0.0, 1.0, "yo", speaker="未割当")]
    text = format_chunk_as_text(segs)
    assert "yo" in text
    assert "未割当:" not in text
