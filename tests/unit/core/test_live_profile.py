"""apply_live_profile() のユニットテスト。"""
from __future__ import annotations

import pytest

from core.cassette import _DEPRECATED_LIVE_NAMES, apply_live_profile, load_cassette


def _minimal_batch_data() -> dict:
    """テスト用の最小カセット dict（sales_meeting 相当の骨子）。"""
    return {
        "name": "test",
        "mode": "cloud_batch",
        "input": {"type": "file", "storage": "local"},
        "pipeline": [
            {"step": "preprocess", "enabled": True, "params": {"noise_reduce_strength": 0.8}},
            {"step": "transcribe", "provider": "faster_whisper_batch", "enabled": True,
             "params": {"model": "large-v3", "beam_size": 5}},
            {"step": "diarize", "provider": "pyannote", "enabled": True,
             "params": {"num_speakers": 2,
                        "speaker_names": {"SPEAKER_00": "自社", "SPEAKER_01": "顧客"}}},
            {"step": "term_correct", "enabled": True, "params": {}},
            {"step": "llm_cleanup", "provider": "claude", "enabled": True, "params": {}},
            {"step": "minutes_extract", "provider": "claude", "enabled": True,
             "params": {"prompt": "prompts/minutes_extract_sales_meeting.md"}},
            {"step": "format", "enabled": True, "params": {}},
        ],
        "llm": {"provider": "claude", "model": "claude-haiku-4-5", "batch_mode": True},
        "output": {"formats": ["md"], "destinations": [{"type": "local", "path": "./out/"}]},
    }


# ─── input 変換 ─────────────────────────────────
def test_input_type_becomes_live_audio():
    d = _minimal_batch_data()
    apply_live_profile(d)
    assert d["input"]["type"] == "live_audio"


def test_input_default_channels_added():
    d = _minimal_batch_data()
    apply_live_profile(d)
    assert len(d["input"]["channels"]) == 2
    assert d["input"]["channels"][0] == {"source": "microphone", "label": "self"}


def test_input_default_mix_is_separate():
    d = _minimal_batch_data()
    apply_live_profile(d)
    assert d["input"]["mix"] == "separate"


def test_input_respects_existing_channels():
    d = _minimal_batch_data()
    d["input"]["channels"] = [{"source": "microphone", "label": "custom"}]
    apply_live_profile(d)
    # ユーザー指定が尊重される
    assert d["input"]["channels"][0]["label"] == "custom"


# ─── llm.batch_mode ──
def test_llm_batch_mode_forced_false():
    d = _minimal_batch_data()
    assert d["llm"]["batch_mode"] is True
    apply_live_profile(d)
    assert d["llm"]["batch_mode"] is False


# ─── preprocess ──
def test_preprocess_switched_to_simple():
    d = _minimal_batch_data()
    apply_live_profile(d)
    pp = next(s for s in d["pipeline"] if s["step"] == "preprocess")
    assert pp["provider"] == "simple"
    assert "loudnorm" in pp["params"]


# ─── transcribe ──
def test_transcribe_switched_to_chunked_turbo():
    d = _minimal_batch_data()
    apply_live_profile(d)
    tr = next(s for s in d["pipeline"] if s["step"] == "transcribe")
    assert tr["provider"] == "faster_whisper_chunked"
    assert tr["params"]["model"] == "large-v3-turbo"
    assert tr["params"]["chunk_sec"] == 20.0
    assert tr["params"]["overlap_sec"] == 2.0


# ─── diarize ──
def test_diarize_switched_to_channel_based():
    d = _minimal_batch_data()
    apply_live_profile(d)
    di = next(s for s in d["pipeline"] if s["step"] == "diarize")
    assert di["provider"] == "channel_based"


def test_diarize_speaker_names_mapped_from_pyannote():
    """pyannote 用 SPEAKER_00/01 が channel_based 用 ch0/ch1 に引き継がれる。"""
    d = _minimal_batch_data()
    apply_live_profile(d)
    di = next(s for s in d["pipeline"] if s["step"] == "diarize")
    assert di["params"]["speaker_names"] == {"ch0": "自社", "ch1": "顧客"}


def test_diarize_disabled_stays_disabled():
    """enabled=false の diarize はプロファイル適用で有効化しない（seminar 用）。"""
    d = _minimal_batch_data()
    for s in d["pipeline"]:
        if s["step"] == "diarize":
            s["enabled"] = False
            s["provider"] = "pyannote"
    apply_live_profile(d)
    di = next(s for s in d["pipeline"] if s["step"] == "diarize")
    assert di["enabled"] is False
    assert di["provider"] == "pyannote"  # 変更されていない


# ─── load_cassette(live=True) 統合 ──
def test_load_cassette_with_live_flag_transforms_inline():
    c = load_cassette("sales_meeting", live=True)
    assert c.input.type == "live_audio"
    assert c.llm.batch_mode is False


def test_load_cassette_without_live_flag_unchanged():
    c = load_cassette("sales_meeting")
    assert c.input.type == "file"
    # sales_meeting.yaml の batch_mode は元々 true
    assert c.llm.batch_mode is True


# ─── deprecation マッピング ──
def test_deprecated_live_name_maps_to_canonical():
    c = load_cassette("live_sales")
    assert c.name == "sales_meeting"
    assert c.input.type == "live_audio"


def test_deprecated_mapping_constants_present():
    assert _DEPRECATED_LIVE_NAMES == {
        "live_sales": "sales_meeting",
        "live_internal": "internal_meeting",
        "one_on_one_live": "one_on_one",
    }


# ─── overrides + live の併用 ──
def test_live_then_override_applies_override_last():
    """live プロファイル適用 → override で追加調整が可能。"""
    c = load_cassette(
        "sales_meeting",
        live=True,
        overrides=["transcribe.params.model=large-v3"],
    )
    # override が live プロファイル後に当たるので model が上書きされる
    assert c.get_step("transcribe").params["model"] == "large-v3"


def test_override_can_downgrade_diarize_back_to_pyannote_with_mix_mono():
    """特殊ケース: 多人数ライブ MTG で pyannote に戻したい。"""
    c = load_cassette(
        "internal_meeting",
        live=True,
        overrides=[
            "input.mix=mono_merge",
            "diarize.provider=pyannote",
        ],
    )
    assert c.input.mix == "mono_merge"
    assert c.get_step("diarize").provider == "pyannote"