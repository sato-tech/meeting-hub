"""ChunkBuffer — 長尺 WAV（または将来の PCM ストリーム）を重複付きチャンクに分解。

設計:
  - chunk_sec = 20.0（Whisper の attention 長、日本語の文境界を跨ぎやすいバランス）
  - overlap_sec = 2.0（前後の重複で境界切れを吸収）
  - 既定の step = chunk_sec - overlap_sec = 18.0 秒進める
  - segments の重複除去は `merge_overlapping_segments()` で後処理
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class ChunkSpec:
    """1 チャンクの仕様。"""
    index: int
    start_sec: float
    end_sec: float
    wav_path: Path

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


class ChunkBuffer:
    """WAV → 重複付きチャンク列に分解。

    Phase 4 は「録音済み WAV を疑似ストリーム化」する用途。
    Phase 5 で真のストリーム（bytes チャンク受信）に拡張予定。
    """

    def __init__(
        self,
        source_wav: Path,
        work_dir: Path,
        *,
        chunk_sec: float = 20.0,
        overlap_sec: float = 2.0,
    ):
        if chunk_sec <= overlap_sec:
            raise ValueError("chunk_sec must be > overlap_sec")
        self.source_wav = Path(source_wav)
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.chunk_sec = float(chunk_sec)
        self.overlap_sec = float(overlap_sec)
        self.step_sec = self.chunk_sec - self.overlap_sec

    def chunks(self) -> Iterator[ChunkSpec]:
        """先頭から順に ChunkSpec を yield する。"""
        import soundfile as sf

        info = sf.info(str(self.source_wav))
        sr = int(info.samplerate)
        total_sec = float(info.frames) / float(sr or 1)
        logger.info(
            "ChunkBuffer: source=%s total=%.1fs chunk=%.1fs overlap=%.1fs",
            self.source_wav.name, total_sec, self.chunk_sec, self.overlap_sec,
        )

        idx = 0
        start = 0.0
        while start < total_sec:
            end = min(start + self.chunk_sec, total_sec)
            out = self.work_dir / f"chunk_{idx:04d}.wav"
            self._write_chunk(sr, start, end, out)
            yield ChunkSpec(index=idx, start_sec=start, end_sec=end, wav_path=out)
            idx += 1
            start += self.step_sec
            if end >= total_sec:
                break

    def _write_chunk(self, sr: int, start_sec: float, end_sec: float, out: Path) -> None:
        """元 WAV から [start_sec, end_sec) を切り出して書き出す。"""
        import soundfile as sf

        start_frame = int(start_sec * sr)
        end_frame = int(end_sec * sr)
        with sf.SoundFile(str(self.source_wav)) as f:
            f.seek(start_frame)
            data = f.read(end_frame - start_frame, dtype="float32")
        sf.write(str(out), data, sr)


def merge_overlapping_segments(
    all_segments: list[list[dict]],
    chunk_spec_list: list[ChunkSpec],
    *,
    dedup_threshold_sec: float = 0.5,
) -> list[dict]:
    """チャンクごとの segments 列をマージ。

    - 各 chunk の segments の時刻は chunk 相対 → chunk.start_sec を足して絶対時刻に
    - 隣接チャンクの重複領域に属する segments は、**前のチャンクを優先**（早く出力されたもの）
    - `dedup_threshold_sec` 以内で start が重なるものは後を削除
    """
    if len(all_segments) != len(chunk_spec_list):
        raise ValueError("segments list length mismatch")

    absolute: list[dict] = []
    for spec, segs in zip(chunk_spec_list, all_segments):
        for seg in segs:
            abs_seg = dict(seg)
            abs_seg["start"] = float(seg["start"]) + spec.start_sec
            abs_seg["end"] = float(seg["end"]) + spec.start_sec
            absolute.append(abs_seg)

    # start でソートした上で、近接のものを削除
    absolute.sort(key=lambda s: float(s["start"]))
    out: list[dict] = []
    last_start = -1e9
    for seg in absolute:
        if float(seg["start"]) - last_start < dedup_threshold_sec:
            continue
        out.append(seg)
        last_start = float(seg["start"])
    return out
