"""preprocess の 2-pass loudnorm テスト（T7 / C8）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.steps.preprocess import (
    DefaultPreprocessStep,
    _build_two_pass_loudnorm_filter,
    _parse_loudnorm_measured,
)


def test_parse_loudnorm_measured_valid():
    stderr = """
    [Parsed_loudnorm_0 @ 0x7f8] {
        "input_i": "-23.4",
        "input_tp": "-3.1",
        "input_lra": "7.8",
        "input_thresh": "-33.4",
        "output_i": "-16.0",
        "target_offset": "0.1"
    }
    """
    m = _parse_loudnorm_measured(stderr)
    assert m is not None
    assert m["input_i"] == "-23.4"


def test_parse_loudnorm_measured_missing():
    assert _parse_loudnorm_measured("no json here") is None


def test_build_two_pass_includes_measured():
    measured = {
        "input_i": "-23.4",
        "input_tp": "-3.1",
        "input_lra": "7.8",
        "input_thresh": "-33.4",
        "target_offset": "0.1",
    }
    spec = _build_two_pass_loudnorm_filter("I=-16:TP=-1.5:LRA=11", measured)
    assert "measured_i=-23.4" in spec
    assert "measured_tp=-3.1" in spec
    assert "linear=true" in spec


def test_two_pass_path_uses_analysis_then_apply(mocker, minimal_cassette, tmp_path):
    """two_pass_loudnorm=true で analysis → apply の 2 回呼ばれる。"""
    src = tmp_path / "input.mp4"
    src.write_bytes(b"fake")

    # ffmpeg existence
    mocker.patch("core.steps.preprocess.shutil.which", return_value="/usr/bin/ffmpeg")

    analysis_stderr = """
    [Parsed_loudnorm_0 @ 0x7f8] {
        "input_i": "-23.4",
        "input_tp": "-3.1",
        "input_lra": "7.8",
        "input_thresh": "-33.4",
        "output_i": "-16.0",
        "target_offset": "0.1"
    }
    """

    call_log = {"n": 0}

    def fake_run(args, capture_output=True, text=True):
        call_log["n"] += 1
        # 1st: analysis（stderr に JSON）、2nd: apply（成果物ファイル作成）
        if call_log["n"] == 1:
            class R:
                returncode = 0
                stdout = ""
                stderr = analysis_stderr
            return R()
        else:
            out = args[-1]
            Path(out).write_bytes(b"x")
            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

    mocker.patch("core.steps.preprocess.subprocess.run", side_effect=fake_run)
    mocker.patch("soundfile.read", return_value=([0.0, 0.1], 16000))
    mocker.patch("soundfile.write")
    mocker.patch("soundfile.info", return_value=type("I", (), {"frames": 16000, "samplerate": 16000})())
    mocker.patch("noisereduce.reduce_noise", side_effect=lambda y, sr, prop_decrease: y)

    ctx = Context(input_path=src, cassette=minimal_cassette, work_dir=tmp_path / "work")
    step = DefaultPreprocessStep(
        provider="default",
        params={"loudnorm": "I=-16:TP=-1.5:LRA=11", "two_pass_loudnorm": True},
    )
    step.process(ctx)

    assert ctx.meta["preprocess"]["loudnorm_mode"] == "two_pass"
    # analysis + apply で少なくとも 2 回呼ばれる
    assert call_log["n"] >= 2


def test_one_pass_is_default(mocker, minimal_cassette, tmp_path):
    src = tmp_path / "input.mp4"
    src.write_bytes(b"fake")
    mocker.patch("core.steps.preprocess.shutil.which", return_value="/usr/bin/ffmpeg")

    def fake_run(args, capture_output=True, text=True):
        Path(args[-1]).write_bytes(b"x")
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    mocker.patch("core.steps.preprocess.subprocess.run", side_effect=fake_run)
    mocker.patch("soundfile.read", return_value=([0.0], 16000))
    mocker.patch("soundfile.write")
    mocker.patch("soundfile.info", return_value=type("I", (), {"frames": 16000, "samplerate": 16000})())
    mocker.patch("noisereduce.reduce_noise", side_effect=lambda y, sr, prop_decrease: y)

    ctx = Context(input_path=src, cassette=minimal_cassette, work_dir=tmp_path / "work")
    step = DefaultPreprocessStep(
        provider="default",
        params={"loudnorm": "I=-16:TP=-1.5:LRA=11"},
    )
    step.process(ctx)
    assert ctx.meta["preprocess"]["loudnorm_mode"] == "one_pass"
