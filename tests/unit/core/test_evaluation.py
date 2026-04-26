"""diarize_benchmark のロジック単体テスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.evaluation import (
    DiarizeBenchmarkResult,
    _load_rttm,
    compute_der,
    emit_decision_report,
    run_benchmark,
)


def test_compute_der_perfect_match():
    ref = [{"start": 0.0, "end": 5.0, "speaker": "A"}, {"start": 5.0, "end": 10.0, "speaker": "B"}]
    hyp = [{"start": 0.0, "end": 5.0, "speaker": "S0"}, {"start": 5.0, "end": 10.0, "speaker": "S1"}]
    # ラベル名が違っても mapping でマッチ
    assert compute_der(hyp, ref) < 0.05


def test_compute_der_zero_overlap():
    ref = [{"start": 0.0, "end": 10.0, "speaker": "A"}]
    hyp = [{"start": 0.0, "end": 10.0, "speaker": "B"}]
    # 1 つの ref に 1 つの hyp → 完全マッチ（マッピングで A↔B）
    assert compute_der(hyp, ref) < 0.05


def test_compute_der_empty_hypothesis():
    ref = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    assert compute_der([], ref) == 1.0


def test_compute_der_empty_reference():
    hyp = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    assert compute_der(hyp, []) == 1.0


def test_load_rttm(tmp_path: Path):
    rttm = tmp_path / "ref.rttm"
    rttm.write_text(
        "\n".join(
            [
                "SPEAKER meeting 1 0.00 5.25 <NA> <NA> SPEAKER_00 <NA> <NA>",
                "SPEAKER meeting 1 5.25 3.00 <NA> <NA> SPEAKER_01 <NA> <NA>",
                "# comment",
            ]
        ),
        encoding="utf-8",
    )
    segs = _load_rttm(rttm)
    assert len(segs) == 2
    assert segs[0]["speaker"] == "SPEAKER_00"
    assert segs[1]["start"] == 5.25
    assert segs[1]["end"] == 8.25


def test_run_benchmark_unknown_provider_skipped(tmp_path: Path):
    # 存在しない provider を渡すと結果に含まれず、エラーでも落ちない
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    results = run_benchmark(wav, reference_rttm=None, providers=["nonexistent"])
    assert results == []


def test_run_benchmark_nemo_missing_skipped(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    # NeMo は未インストール → 例外で捕捉され、リストには含まれない
    results = run_benchmark(wav, reference_rttm=None, providers=["nemo"])
    assert results == []


def _make_result(provider: str, der: float, elapsed: float, sp: int = 2) -> DiarizeBenchmarkResult:
    return DiarizeBenchmarkResult(
        provider=provider,
        der=der,
        total_duration_sec=300.0,
        num_speakers_detected=sp,
        elapsed_sec=elapsed,
        extra={},
    )


def test_emit_decision_report_recommends_pyannote_when_nemo_absent(tmp_path: Path):
    results = [_make_result("pyannote", 0.12, 60.0)]
    md = emit_decision_report(results, output_path=tmp_path / "out.md")
    assert "pyannote 継続を推奨" in md
    assert (tmp_path / "out.md").exists()


def test_emit_decision_report_recommends_nemo_when_strictly_better():
    results = [
        _make_result("pyannote", 0.20, 100.0),
        _make_result("nemo", 0.10, 120.0),
    ]
    md = emit_decision_report(results, der_threshold=0.05, speed_threshold_ratio=0.7)
    assert "NeMo 切替推奨" in md


def test_emit_decision_report_keeps_pyannote_when_nemo_too_slow():
    results = [
        _make_result("pyannote", 0.20, 100.0),
        _make_result("nemo", 0.10, 400.0),
    ]
    md = emit_decision_report(results, speed_threshold_ratio=0.7)
    assert "pyannote 継続" in md


def test_emit_decision_report_keeps_pyannote_when_no_pyannote():
    results = [_make_result("nemo", 0.1, 100.0)]
    md = emit_decision_report(results)
    assert "判断不能" in md
