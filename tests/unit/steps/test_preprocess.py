"""preprocess Step のユニットテスト。

subprocess を mock し、ffmpeg の組立だけを検証する。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.steps.base import Step
from core.steps.preprocess import DefaultPreprocessStep, SimplePreprocessStep  # noqa: F401


@pytest.fixture
def fake_input(tmp_path: Path) -> Path:
    src = tmp_path / "sample.mp4"
    src.write_bytes(b"fake mp4 bytes")
    return src


def _setup_mocks(mocker, output_bytes: bytes = b"fakewavdata"):
    # ffmpeg 存在検出
    mocker.patch("core.steps.preprocess.shutil.which", return_value="/usr/bin/ffmpeg")

    # subprocess.run は常に成功を返し、出力 WAV を副作用で作成
    def fake_run(args, capture_output=True, text=True):
        # ffmpeg 出力先（最後の引数）に空ファイル生成
        out = args[-1]
        Path(out).write_bytes(output_bytes)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    mocker.patch("core.steps.preprocess.subprocess.run", side_effect=fake_run)


def test_default_preprocess_sets_audio_path(mocker, fake_input: Path, tmp_path: Path, minimal_cassette) -> None:
    _setup_mocks(mocker)
    # noisereduce 系は重いので全て fake
    mocker.patch("soundfile.read", return_value=([0.0, 0.1, 0.2], 16000))
    mocker.patch("soundfile.write")
    mocker.patch("soundfile.info", return_value=type("I", (), {"frames": 16000, "samplerate": 16000})())
    mocker.patch("noisereduce.reduce_noise", side_effect=lambda y, sr, prop_decrease: y)

    ctx = Context(input_path=fake_input, cassette=minimal_cassette, work_dir=tmp_path / "work")
    step = DefaultPreprocessStep(provider="default", params={"target_sr": 16000})
    out = step.process(ctx)
    assert out.audio_path is not None
    assert out.audio_path.name == "sample_clean.wav"
    assert out.meta["preprocess"]["provider"] == "default"
    assert out.meta["preprocess"]["sample_rate"] == 16000
    assert "preprocess" in out.meta["timings"]


def test_simple_preprocess_uses_loudnorm(mocker, fake_input: Path, tmp_path: Path, minimal_cassette) -> None:
    _setup_mocks(mocker)
    mocker.patch("soundfile.info", return_value=type("I", (), {"frames": 16000, "samplerate": 16000})())

    captured = {}

    def capture_run(args, capture_output=True, text=True):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"x")
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    mocker.patch("core.steps.preprocess.subprocess.run", side_effect=capture_run)

    ctx = Context(input_path=fake_input, cassette=minimal_cassette, work_dir=tmp_path / "work")
    step = SimplePreprocessStep(provider="simple", params={"loudnorm": "I=-16:TP=-1.5:LRA=11", "denoise": True})
    step.process(ctx)

    joined = " ".join(captured["args"])
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in joined
    assert "afftdn" in joined  # denoise=True で afftdn チェーンが入る


def test_preprocess_registered_via_factory(minimal_cassette) -> None:
    from core.cassette_schema import StepConfig
    cfg = StepConfig(step="preprocess", provider="default", params={"target_sr": 16000})
    step = Step.create(cfg)
    assert isinstance(step, DefaultPreprocessStep)
