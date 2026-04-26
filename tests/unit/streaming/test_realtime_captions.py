"""realtime_captions のテスト。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.streaming.realtime_captions import (
    CaptionBroadcaster,
    render_segment,
    render_segments,
    write_live_caption_file,
)


def _seg(start: float, end: float, text: str, speaker: str = "A") -> dict:
    return {"start": start, "end": end, "text": text, "speaker": speaker}


# ─── render_segment ──────────────────
def test_render_segment_plain():
    out = render_segment(_seg(0.0, 1.0, "hello"))
    assert "[0.0-1.0s]" in out
    assert "A: hello" in out


def test_render_segment_plain_skips_unassigned_speaker():
    out = render_segment(_seg(0.0, 1.0, "x", speaker="未割当"))
    assert "未割当:" not in out


def test_render_segment_srt_format():
    out = render_segment(_seg(0.0, 3.5, "yo"), fmt="srt", index=1)
    assert out.startswith("1\n")
    assert "00:00:00,000 --> 00:00:03,500" in out


def test_render_segment_vtt_format():
    out = render_segment(_seg(65.5, 66.0, "yo"), fmt="vtt")
    assert "00:01:05.500 --> 00:01:06.000" in out
    assert "<v A>" in out


def test_render_segment_json():
    out = render_segment(_seg(0.0, 1.0, "yo"), fmt="json")
    parsed = json.loads(out)
    assert parsed["start"] == 0.0
    assert parsed["text"] == "yo"


# ─── render_segments ─────────────────
def test_render_segments_vtt_has_header():
    segs = [_seg(0.0, 1.0, "a"), _seg(1.0, 2.0, "b")]
    out = render_segments(segs, fmt="vtt")
    assert out.startswith("WEBVTT")


def test_render_segments_json_array():
    segs = [_seg(0.0, 1.0, "a"), _seg(1.0, 2.0, "b")]
    out = render_segments(segs, fmt="json")
    parsed = json.loads(out)
    assert len(parsed) == 2
    assert parsed[0]["text"] == "a"


def test_render_segments_srt_indices_auto_numbered():
    segs = [_seg(0.0, 1.0, "a"), _seg(2.0, 3.0, "b")]
    out = render_segments(segs, fmt="srt")
    assert out.startswith("1\n")
    assert "\n2\n" in out


# ─── CaptionBroadcaster ──────────────
def test_broadcaster_feed_distributes_to_subscribers():
    b = CaptionBroadcaster()
    received_a: list[dict] = []
    received_b: list[dict] = []
    b.subscribe(received_a.append)
    b.subscribe(received_b.append)
    b.feed([_seg(0.0, 1.0, "hello")])
    assert received_a == [_seg(0.0, 1.0, "hello")]
    assert received_b == [_seg(0.0, 1.0, "hello")]
    assert b.snapshot() == [_seg(0.0, 1.0, "hello")]


def test_broadcaster_unsubscribe():
    b = CaptionBroadcaster()
    received: list[dict] = []
    b.subscribe(received.append)
    b.unsubscribe(received.append)
    b.feed([_seg(0.0, 1.0, "hello")])
    assert received == []


def test_broadcaster_subscriber_exception_is_swallowed():
    b = CaptionBroadcaster()
    received: list[dict] = []

    def crashes(seg):
        raise RuntimeError("boom")

    b.subscribe(crashes)
    b.subscribe(received.append)
    b.feed([_seg(0.0, 1.0, "hello")])
    # 2 番目は通る
    assert len(received) == 1


def test_broadcaster_export_srt(tmp_path: Path):
    b = CaptionBroadcaster()
    b.feed([_seg(0.0, 1.0, "a"), _seg(1.5, 2.5, "b")])
    out = b.export(tmp_path / "live.srt", fmt="srt")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("1\n")
    assert "A: a" in text


def test_broadcaster_export_vtt(tmp_path: Path):
    b = CaptionBroadcaster()
    b.feed([_seg(0.0, 1.0, "a")])
    out = b.export(tmp_path / "live.vtt", fmt="vtt")
    assert out.read_text(encoding="utf-8").startswith("WEBVTT")


# ─── write_live_caption_file ────────
def test_write_live_caption_file_appends(tmp_path: Path):
    b = CaptionBroadcaster()
    path = tmp_path / "out.srt"
    handler = write_live_caption_file(b, path, fmt="srt")
    b.subscribe(handler)
    b.feed([_seg(0.0, 1.0, "a"), _seg(1.5, 2.5, "b")])
    content = path.read_text(encoding="utf-8")
    assert "1\n" in content
    assert "2\n" in content
