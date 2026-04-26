"""ChunkBuffer と merge_overlapping_segments のテスト。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from core.streaming.buffer import (
    ChunkBuffer,
    ChunkSpec,
    merge_overlapping_segments,
)


def _write_sine_wav(path: Path, duration_sec: float, sr: int = 16000) -> None:
    t = np.linspace(0, duration_sec, int(duration_sec * sr), endpoint=False)
    data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(str(path), data, sr)


def test_chunk_buffer_splits_with_overlap(tmp_path: Path) -> None:
    wav = tmp_path / "src.wav"
    _write_sine_wav(wav, duration_sec=50.0)
    buf = ChunkBuffer(wav, tmp_path / "chunks", chunk_sec=20.0, overlap_sec=2.0)
    specs = list(buf.chunks())
    assert len(specs) >= 3
    # step = 18.0、最初のチャンクは 0〜20
    assert specs[0].start_sec == 0.0
    assert abs(specs[0].end_sec - 20.0) < 0.1
    # 2 番目は 18〜38
    assert abs(specs[1].start_sec - 18.0) < 0.1
    # チャンクファイルが生成されている
    for s in specs:
        assert s.wav_path.exists()


def test_chunk_buffer_rejects_bad_params(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ChunkBuffer(tmp_path / "x.wav", tmp_path, chunk_sec=2.0, overlap_sec=5.0)


def test_merge_overlapping_segments_absolute_time() -> None:
    # chunk0: 0〜20s → seg 5〜10
    # chunk1: 18〜38s → seg 5〜10（絶対時刻 23〜28）
    spec0 = ChunkSpec(0, 0.0, 20.0, Path("c0"))
    spec1 = ChunkSpec(1, 18.0, 38.0, Path("c1"))
    segs0 = [{"start": 5.0, "end": 10.0, "text": "a", "speaker": "A"}]
    segs1 = [{"start": 5.0, "end": 10.0, "text": "b", "speaker": "B"}]
    merged = merge_overlapping_segments([segs0, segs1], [spec0, spec1])
    # 5.0 と 23.0 で 18秒離れているので両方残る
    starts = [s["start"] for s in merged]
    assert 5.0 in starts
    assert 23.0 in starts


def test_merge_overlapping_dedup_close_starts() -> None:
    spec0 = ChunkSpec(0, 0.0, 20.0, Path("c0"))
    spec1 = ChunkSpec(1, 18.0, 38.0, Path("c1"))
    # 前: 19.0 / 後: 19.3（絶対時刻 19.3 で重複）
    segs0 = [{"start": 19.0, "end": 19.5, "text": "a", "speaker": "A"}]
    segs1 = [{"start": 1.3, "end": 2.0, "text": "b", "speaker": "B"}]  # 絶対 19.3
    merged = merge_overlapping_segments([segs0, segs1], [spec0, spec1], dedup_threshold_sec=0.5)
    assert len(merged) == 1  # 後を削除
    assert merged[0]["text"] == "a"


def test_chunk_buffer_short_source_produces_one_chunk(tmp_path: Path) -> None:
    wav = tmp_path / "s.wav"
    _write_sine_wav(wav, duration_sec=5.0)
    specs = list(ChunkBuffer(wav, tmp_path / "out").chunks())
    assert len(specs) == 1
    assert specs[0].start_sec == 0.0
    assert specs[0].end_sec == 5.0
