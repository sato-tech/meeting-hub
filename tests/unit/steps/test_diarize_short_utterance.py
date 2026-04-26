"""短発話・話者切替対応の追加テスト（P4 + P5）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.context import Context
from core.steps.diarize import PyannoteDiarizeStep


# ─── P4: pyannote ハイパーパラメータ配線 ──
def test_instantiate_hyperparams_called_when_segmentation_threshold_set():
    """segmentation_threshold が params にあれば pipeline.instantiate に渡される。"""
    step = PyannoteDiarizeStep(
        provider="pyannote",
        params={"segmentation_threshold": 0.35, "min_duration_on": 0.0},
    )
    fake_pipeline = MagicMock()
    step._instantiate_hyperparams(fake_pipeline)
    fake_pipeline.instantiate.assert_called_once()
    call_arg = fake_pipeline.instantiate.call_args.args[0]
    assert call_arg["segmentation"]["threshold"] == 0.35
    assert call_arg["segmentation"]["min_duration_on"] == 0.0


def test_instantiate_hyperparams_clustering_only():
    step = PyannoteDiarizeStep(
        provider="pyannote",
        params={"clustering_threshold": 0.6, "min_cluster_size": 8},
    )
    fake = MagicMock()
    step._instantiate_hyperparams(fake)
    arg = fake.instantiate.call_args.args[0]
    assert "clustering" in arg
    assert arg["clustering"]["threshold"] == 0.6
    assert arg["clustering"]["min_cluster_size"] == 8
    assert "segmentation" not in arg


def test_instantiate_hyperparams_skipped_when_no_keys():
    """カセット params が無関係なら instantiate は呼ばれない。"""
    step = PyannoteDiarizeStep(provider="pyannote", params={"num_speakers": 2})
    fake = MagicMock()
    step._instantiate_hyperparams(fake)
    fake.instantiate.assert_not_called()


def test_instantiate_hyperparams_failure_logs_warning_no_raise(caplog):
    """instantiate が例外を投げてもパイプラインロード自体は壊さない。"""
    step = PyannoteDiarizeStep(provider="pyannote", params={"segmentation_threshold": 0.4})
    fake = MagicMock()
    fake.instantiate.side_effect = RuntimeError("hyperparam config invalid")
    # 例外を伝播させないことを確認
    step._instantiate_hyperparams(fake)


# ─── P5: word-level speaker で segment 分割 ──
def test_split_segment_by_word_speakers_simple_two_speakers():
    orig = {"start": 0.0, "end": 5.0, "text": "Hello there", "speaker": "未割当"}
    words = [
        {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"word": " there", "start": 3.0, "end": 5.0, "speaker": "SPEAKER_01"},
    ]
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(
        orig, words, {"SPEAKER_00": "自社", "SPEAKER_01": "顧客"}
    )
    assert len(out) == 2
    assert out[0]["speaker"] == "自社"
    assert out[1]["speaker"] == "顧客"
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 1.0
    assert out[1]["start"] == 3.0
    assert out[1]["end"] == 5.0


def test_split_segment_groups_consecutive_same_speaker():
    """同 speaker が連続する word はまとめる。A,A,B,B,A → 3 つのサブ segment。"""
    orig = {"start": 0.0, "end": 5.0, "text": "abc"}
    words = [
        {"word": "a", "start": 0.0, "end": 1.0, "speaker": "A"},
        {"word": "b", "start": 1.0, "end": 2.0, "speaker": "A"},
        {"word": "c", "start": 2.0, "end": 3.0, "speaker": "B"},
        {"word": "d", "start": 3.0, "end": 4.0, "speaker": "B"},
        {"word": "e", "start": 4.0, "end": 5.0, "speaker": "A"},
    ]
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(orig, words, {})
    assert len(out) == 3
    assert [s["speaker"] for s in out] == ["A", "B", "A"]


def test_split_segment_unknown_speaker_inherits_previous():
    orig = {"start": 0.0, "end": 3.0, "text": "x"}
    words = [
        {"word": "a", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"word": "b", "start": 1.0, "end": 2.0},  # speaker 不明
        {"word": "c", "start": 2.0, "end": 3.0, "speaker": "SPEAKER_01"},
    ]
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(orig, words, {})
    # speaker 不明な word は直前の SPEAKER_00 を継承するので [SPEAKER_00, SPEAKER_01] の 2 group
    assert [s["speaker"] for s in out] == ["SPEAKER_00", "SPEAKER_01"]


def test_split_segment_empty_words_returns_orig_copy():
    orig = {"start": 0.0, "end": 1.0, "text": "x", "speaker": "A"}
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(orig, [], {})
    assert len(out) == 1
    assert out[0]["start"] == 0.0


def test_split_segment_falls_back_to_uniform_distribution_without_word_timestamps():
    """word に start/end が無い場合は orig 区間を均等分割。"""
    orig = {"start": 0.0, "end": 6.0, "text": "x"}
    words = [
        {"word": "a", "speaker": "A"},
        {"word": "b", "speaker": "B"},
    ]
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(orig, words, {})
    assert len(out) == 2
    # 0.0-3.0, 3.0-6.0 で均等分割
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 3.0
    assert out[1]["start"] == 3.0
    assert out[1]["end"] == 6.0


def test_split_segment_text_concatenated_from_words():
    orig = {"start": 0.0, "end": 2.0, "text": "(original)"}
    words = [
        {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "A"},
        {"word": " world", "start": 1.0, "end": 2.0, "speaker": "A"},
    ]
    out = PyannoteDiarizeStep._split_segment_by_word_speakers(orig, words, {})
    assert len(out) == 1
    assert out[0]["text"] == "Hello world"  # word を結合 + strip


# ─── P5 統合: _apply_with_whisperx_align で split が走る ──
def test_align_path_splits_segment_when_word_speakers_differ(monkeypatch, minimal_cassette, tmp_path):
    """whisperx align モードで word の speaker が異なる場合、segment が増える。"""
    step = PyannoteDiarizeStep(
        provider="pyannote",
        params={"split_on_speaker_change": True},
    )
    monkeypatch.setattr(step, "_load_pipeline", lambda: lambda audio, **kw: MagicMock())

    fake_wx = MagicMock()
    fake_wx.load_audio.return_value = b"audio"
    fake_wx.load_align_model.return_value = (MagicMock(), MagicMock())
    fake_wx.align.return_value = {"segments": []}
    # 1 つの input segment が word-level で 2 speaker に分かれる
    fake_wx.assign_word_speakers.return_value = {
        "segments": [
            {
                "speaker": "SPEAKER_00",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": " world", "start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"},
                ],
            }
        ]
    }
    monkeypatch.setitem(sys.modules, "whisperx", fake_wx)

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav)
    ctx.segments = [{"start": 0.0, "end": 4.0, "text": "Hello world", "speaker": "未割当"}]
    step.process(ctx)

    # 元 1 segment → 2 segments に分割される
    assert len(ctx.segments) == 2
    assert ctx.segments[0]["speaker"] == "SPEAKER_00"
    assert ctx.segments[1]["speaker"] == "SPEAKER_01"


def test_split_disabled_keeps_single_segment(monkeypatch, minimal_cassette, tmp_path):
    """split_on_speaker_change=false なら従来通り 1 segment 維持。"""
    step = PyannoteDiarizeStep(
        provider="pyannote",
        params={"split_on_speaker_change": False},
    )
    monkeypatch.setattr(step, "_load_pipeline", lambda: lambda audio, **kw: MagicMock())

    fake_wx = MagicMock()
    fake_wx.load_audio.return_value = b"audio"
    fake_wx.load_align_model.return_value = (MagicMock(), MagicMock())
    fake_wx.align.return_value = {"segments": []}
    fake_wx.assign_word_speakers.return_value = {
        "segments": [
            {
                "speaker": "SPEAKER_00",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": " world", "start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"},
                ],
            }
        ]
    }
    monkeypatch.setitem(sys.modules, "whisperx", fake_wx)

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav)
    ctx.segments = [{"start": 0.0, "end": 4.0, "text": "Hello world", "speaker": "未割当"}]
    step.process(ctx)

    # split されないので 1 segment のまま
    assert len(ctx.segments) == 1
