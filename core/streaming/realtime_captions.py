"""realtime_captions — partial segments を live caption 形式にフォーマット + broadcast。

Phase 5 の主目的:
  - `StreamingJob.partial_events` や `transcribe_on_partial` callback から流れてくる segments を
    SRT / VTT / plain / json の各形式でリアルタイム整形
  - CaptionBroadcaster が複数のサブスクライバ（UI、ファイル書き出し、WebSocket など）に配信

設計:
  - CaptionRenderer は **純関数的**（1 segment → formatted string）
  - CaptionBroadcaster は **スレッドセーフ**（threading.Lock）
  - Streamlit / CLI / ファイル書込の 3 用途を同じ API で満たす
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

logger = logging.getLogger(__name__)


CaptionFormat = Literal["plain", "srt", "vtt", "json"]


def _srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")


def _vtt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02}:{m:02}:{s:06.3f}"


def render_segment(
    seg: dict,
    *,
    fmt: CaptionFormat = "plain",
    index: int = 1,
) -> str:
    """1 セグメントを指定フォーマットで整形。"""
    start = float(seg["start"])
    end = float(seg["end"])
    speaker = seg.get("speaker") or ""
    text = seg.get("text", "")

    if fmt == "plain":
        prefix = f"[{start:.1f}-{end:.1f}s] "
        sp = f"{speaker}: " if speaker and speaker != "未割当" else ""
        return f"{prefix}{sp}{text}"

    if fmt == "srt":
        sp = f"{speaker}: " if speaker and speaker != "未割当" else ""
        return f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{sp}{text}\n"

    if fmt == "vtt":
        sp = f"<v {speaker}>" if speaker and speaker != "未割当" else ""
        return f"{_vtt_time(start)} --> {_vtt_time(end)}\n{sp}{text}\n"

    if fmt == "json":
        return json.dumps(
            {"start": start, "end": end, "speaker": speaker, "text": text},
            ensure_ascii=False,
        )

    raise ValueError(f"Unknown format: {fmt}")


def render_segments(segments: list[dict], *, fmt: CaptionFormat = "plain") -> str:
    """複数セグメントを結合。SRT は index の連番が自動で振られる。"""
    if fmt == "vtt":
        body = "\n".join(render_segment(s, fmt=fmt) for s in segments)
        return f"WEBVTT\n\n{body}"
    if fmt == "json":
        return json.dumps(
            [
                {
                    "start": float(s["start"]),
                    "end": float(s["end"]),
                    "speaker": s.get("speaker") or "",
                    "text": s.get("text", ""),
                }
                for s in segments
            ],
            ensure_ascii=False,
            indent=2,
        )
    lines = [render_segment(s, fmt=fmt, index=i) for i, s in enumerate(segments, 1)]
    return "\n".join(lines) if fmt == "plain" else "\n".join(lines)


@dataclass
class CaptionBroadcaster:
    """複数のサブスクライバに caption を配信するスレッドセーフなハブ。

    - `subscribe(fn)` で `(segment: dict) -> None` を受け取る関数を登録
    - `feed(segments)` で新しい partial を流し込む
    - `export(path, fmt)` で累積した全 segments をファイル化
    """

    segments: list[dict] = field(default_factory=list)
    _subscribers: list[Callable[[dict], None]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(fn)
            except ValueError:
                pass

    def feed(self, segments: list[dict]) -> None:
        """新しい partial segments を全 subscriber にブロードキャスト。"""
        with self._lock:
            subs = list(self._subscribers)
            self.segments.extend(segments)
        for seg in segments:
            for fn in subs:
                try:
                    fn(seg)
                except Exception:
                    logger.exception("subscriber raised (ignored)")

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.segments)

    def export(self, path: Path, fmt: CaptionFormat = "srt") -> Path:
        """累積した全 segments を path に書き出す。"""
        snap = self.snapshot()
        text = render_segments(snap, fmt=fmt)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def write_live_caption_file(broadcaster: CaptionBroadcaster, path: Path, fmt: CaptionFormat = "srt") -> Callable[[dict], None]:
    """subscriber: 1 segment 来るたびに path に追記（簡易、SRT/plain 向け）。

    VTT/JSON は追記に向かないため export() でまとめて書き出し推奨。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def handler(seg: dict) -> None:
        counter["n"] += 1
        line = render_segment(seg, fmt=fmt, index=counter["n"])
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    return handler
