"""B6: chunk 文末境界優先のテスト。"""
from __future__ import annotations

from core.steps.llm_cleanup import (
    _ends_with_sentence_terminator,
    chunk_segments,
)


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text, "speaker": "A"}


def test_ends_with_sentence_terminator_japanese():
    assert _ends_with_sentence_terminator("こんにちは。")
    assert _ends_with_sentence_terminator("どうですか？")
    assert _ends_with_sentence_terminator("素晴らしい！")


def test_ends_with_sentence_terminator_english():
    assert _ends_with_sentence_terminator("Hello.")
    assert _ends_with_sentence_terminator("Really?")
    assert _ends_with_sentence_terminator("Yes!")


def test_does_not_end_with_terminator():
    assert not _ends_with_sentence_terminator("これは途中")
    assert not _ends_with_sentence_terminator("")


def test_chunk_prefers_sentence_boundary_over_gap():
    # soft=500 を超えた直後に「文末で終わる segment」があれば、そこで区切る
    segs = [
        _seg(0.0, 1.0, "a" * 600),             # soft 超え、文末でない（prev_text）
        _seg(1.1, 2.0, "句読点で終わる。"),      # ここで区切るべき（文末）
        _seg(2.2, 3.0, "次の内容"),              # 次の chunk 先頭
    ]
    chunks = chunk_segments(segs, max_chars=2000, soft_chars=500, preferred_gap=5.0)
    # 従来挙動（gap=5.0 は満たさない）では 1 chunk、新挙動では 2 chunk に分かれる
    assert len(chunks) == 2
    assert chunks[0][-1]["text"] == "句読点で終わる。"
    assert chunks[1][0]["text"] == "次の内容"


def test_chunk_legacy_mode_without_sentence_boundary():
    segs = [
        _seg(0.0, 1.0, "a" * 600),
        _seg(1.1, 2.0, "句読点で終わる。"),
        _seg(2.2, 3.0, "次の内容"),
    ]
    chunks = chunk_segments(
        segs, max_chars=2000, soft_chars=500, preferred_gap=5.0,
        prefer_sentence_boundary=False,
    )
    # prefer_sentence_boundary=False で従来挙動（gap が無く max_chars も越えてないので 1 chunk）
    assert len(chunks) == 1


def test_chunk_still_respects_max_chars():
    segs = [_seg(0.0, 1.0, "a" * 900), _seg(1.1, 2.0, "b" * 900), _seg(2.1, 3.0, "c" * 900)]
    chunks = chunk_segments(segs, max_chars=1500, soft_chars=1200, preferred_gap=5.0)
    assert len(chunks) >= 2
    for c in chunks:
        assert sum(len(s["text"]) for s in c) <= 1500
