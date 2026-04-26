"""A1（hallucination 拡充）+ A4（initial_prompt 自動選択）+ B9（VAD リトライ拡張）のテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.steps.transcribe import (
    DEFAULT_HALLUCINATION_PATTERNS,
    FasterWhisperBatchStep,
    _compute_initial_prompt,
    is_hallucination,
    resolve_default_initial_prompt_file,
)


# ─── A1: 拡充パターン ─────────────────────
def test_hallucination_pattern_subtitle_credit():
    assert is_hallucination("字幕は〇〇が担当しました", DEFAULT_HALLUCINATION_PATTERNS)


def test_hallucination_pattern_contact():
    assert is_hallucination("お問い合わせは以下まで", DEFAULT_HALLUCINATION_PATTERNS)


def test_hallucination_pattern_repeat_long_block():
    # 3文字ブロック × 4回繰返し（ABC ABC ABC ABC）
    assert is_hallucination("テストテストテストテスト", DEFAULT_HALLUCINATION_PATTERNS)


def test_hallucination_pattern_new_patterns_listed():
    # 追加した 3 件が定数に含まれていることを確認
    combined = "|".join(DEFAULT_HALLUCINATION_PATTERNS)
    assert "字幕は" in combined
    assert "お問い合わせは" in combined


# ─── A4: cassette 名から initial_prompt 自動選択 ──
def test_resolve_default_initial_prompt_for_seminar():
    got = resolve_default_initial_prompt_file("seminar")
    assert got is not None
    assert "seminar.txt" in got


def test_resolve_default_initial_prompt_for_sales_meeting():
    got = resolve_default_initial_prompt_file("sales_meeting")
    assert got is not None
    assert "business.txt" in got


def test_resolve_default_initial_prompt_for_unknown():
    assert resolve_default_initial_prompt_file("__unknown__") is None


def test_compute_initial_prompt_uses_cassette_default(tmp_path, monkeypatch):
    # vocab/initial_prompts/seminar.txt は実在するので seminar を指定するだけでロードされる
    prompt = _compute_initial_prompt({}, cassette_name="seminar")
    assert prompt is not None
    assert "NISA" in prompt or "iDeCo" in prompt or "セミナー" in prompt


def test_compute_initial_prompt_explicit_file_overrides_cassette(tmp_path):
    my_file = tmp_path / "mine.txt"
    my_file.write_text("MY PROMPT", encoding="utf-8")
    prompt = _compute_initial_prompt(
        {"initial_prompt_file": str(my_file)},
        cassette_name="seminar",  # これよりファイル優先
    )
    assert prompt == "MY PROMPT"


def test_compute_initial_prompt_direct_concatenated_with_cassette(tmp_path):
    # cassette fallback + direct の両方が結合される
    prompt = _compute_initial_prompt(
        {"initial_prompt": "ADDITIONAL"},
        cassette_name="seminar",
    )
    assert prompt is not None
    assert "ADDITIONAL" in prompt
    # cassette fallback 由来のキーワードも入る
    assert any(kw in prompt for kw in ["NISA", "セミナー", "iDeCo"])


def test_compute_initial_prompt_none_when_no_params_no_cassette():
    assert _compute_initial_prompt({}, cassette_name=None) is None
    # unknown cassette も None
    assert _compute_initial_prompt({}, cassette_name="__unknown__") is None


# ─── B9: VAD リトライ拡張（文字数不足時も再試行） ──
def test_vad_retry_triggers_on_too_few_chars(mocker, minimal_cassette, tmp_path):
    """total_chars < min_retry_chars の場合にリトライが走ることを _run_once 呼び出し回数で確認。"""
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")
    step = FasterWhisperBatchStep(
        provider="faster_whisper_batch",
        params={"min_retry_chars": 10, "retry_vad_threshold": 0.3},
    )
    # 1 回目は 1 文字だけ、2 回目（リトライ）は普通
    calls = {"n": 0}

    def fake_run_once(audio_path, vad_threshold, cassette_name=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"start": 0.0, "end": 1.0, "text": "あ", "speaker": "未割当", "no_speech_prob": 0.1}]
        return [{"start": 0.0, "end": 2.0, "text": "これは十分な長さのテキストです", "speaker": "未割当", "no_speech_prob": 0.1}]

    mocker.patch.object(step, "_run_once", side_effect=fake_run_once)

    from core.context import Context
    ctx = Context(input_path=wav, cassette=minimal_cassette, audio_path=wav, work_dir=tmp_path)
    step.process(ctx)
    assert calls["n"] == 2
    assert any("retry_with_vad_threshold" in w for w in ctx.meta.get("warnings", []))
