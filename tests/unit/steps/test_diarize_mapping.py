"""diarize Step の speaker_names マッピング純関数テスト。"""
from __future__ import annotations

from core.steps.diarize import PyannoteDiarizeStep


class FakeTurn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class FakeDiarization:
    """itertracks(yield_label=True) を模擬。"""

    def __init__(self, tracks: list[tuple[FakeTurn, str, str]]):
        self._tracks = tracks

    def itertracks(self, yield_label: bool = False):
        if yield_label:
            yield from self._tracks
        else:
            for t, track, _spk in self._tracks:
                yield t, track


def test_apply_maps_speaker_labels() -> None:
    step = PyannoteDiarizeStep(provider="pyannote", params={})
    diar = FakeDiarization(
        [
            (FakeTurn(0.0, 2.0), "t0", "SPEAKER_00"),
            (FakeTurn(2.0, 4.0), "t1", "SPEAKER_01"),
        ]
    )
    segs = [
        {"start": 0.0, "end": 1.5, "text": "hi", "speaker": "未割当"},
        {"start": 2.0, "end": 3.0, "text": "yo", "speaker": "未割当"},
    ]
    out = step._apply_to_segments(segs, diar, {"SPEAKER_00": "自社", "SPEAKER_01": "顧客"})
    assert out[0]["speaker"] == "自社"
    assert out[1]["speaker"] == "顧客"


def test_apply_unknown_when_no_overlap() -> None:
    step = PyannoteDiarizeStep(provider="pyannote", params={})
    diar = FakeDiarization([(FakeTurn(0.0, 1.0), "t", "SPEAKER_00")])
    segs = [{"start": 5.0, "end": 6.0, "text": "x", "speaker": "未割当"}]
    out = step._apply_to_segments(segs, diar, {"SPEAKER_00": "自社"})
    assert out[0]["speaker"] == "UNKNOWN"


def test_apply_without_speaker_names_maps_raw_label() -> None:
    step = PyannoteDiarizeStep(provider="pyannote", params={})
    diar = FakeDiarization([(FakeTurn(0.0, 2.0), "t0", "SPEAKER_00")])
    segs = [{"start": 0.5, "end": 1.5, "text": "x", "speaker": "未割当"}]
    out = step._apply_to_segments(segs, diar, {})
    assert out[0]["speaker"] == "SPEAKER_00"
