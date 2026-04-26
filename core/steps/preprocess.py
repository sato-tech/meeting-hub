"""preprocess Step — 音声前処理。

Provider:
  - default: ffmpeg + noisereduce + librosa（rich。transcription-pipeline 由来）
  - simple:  ffmpeg のみ + loudnorm（軽量。seminar-transcription 由来）
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.steps.base import Step

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise EnvironmentError(
            "ffmpeg is not installed or not in PATH. Install via `brew install ffmpeg`."
        )


def _run_ffmpeg(args: list[str]) -> None:
    logger.debug("ffmpeg: %s", " ".join(args))
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}):\n{proc.stderr}")


def _output_wav_path(ctx: Context) -> Path:
    stem = ctx.input_path.stem
    return ctx.work_dir / f"{stem}_clean.wav"


def _run_ffmpeg_capture(args: list[str]) -> tuple[int, str, str]:
    """stdout / stderr を捕捉して返す（loudnorm measured 抽出用）。"""
    logger.debug("ffmpeg: %s", " ".join(args))
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _parse_loudnorm_measured(stderr: str) -> dict[str, str] | None:
    """loudnorm -af の print_format=json 出力から measured_* を抽出。"""
    import json
    import re

    # ffmpeg loudnorm は stderr の最後に JSON を吐く
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _build_two_pass_loudnorm_filter(loudnorm_spec: str, measured: dict[str, str]) -> str:
    """2-pass 目の loudnorm フィルタ spec を組み立てる。"""
    # spec が "I=-16:TP=-1.5:LRA=11" のときは measured_* を付ける
    parts = [f"loudnorm={loudnorm_spec}"]
    # measured_ フィールドをフィルタに渡す
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if k in measured:
            parts[-1] += f":measured_{k[len('input_'):]}={measured[k]}" if k.startswith("input_") else f":{k}={measured[k]}"
    parts[-1] += ":linear=true:print_format=summary"
    return parts[0]


@Step.register("preprocess", "default")
class DefaultPreprocessStep(Step):
    """ffmpeg → noisereduce → librosa の3段構成（rich）。

    params:
      target_sr (int, default 16000)
      noise_reduce_strength (float, default 0.8): 0.0-1.0
      loudnorm (str, optional): ffmpeg loudnorm filter spec（指定時のみ適用）
      two_pass_loudnorm (bool, default False): True なら 1st pass で measured を取り
                                                2nd pass で適用（長尺で精度向上）
    """

    default_provider = "default"

    def process(self, ctx: Context) -> Context:
        _check_ffmpeg()
        t0 = time.monotonic()

        sr: int = int(self.params.get("target_sr", 16000))
        strength: float = float(self.params.get("noise_reduce_strength", 0.8))
        loudnorm: str | None = self.params.get("loudnorm")
        two_pass = bool(self.params.get("two_pass_loudnorm", False)) and loudnorm is not None

        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        raw_wav = ctx.work_dir / f"{ctx.input_path.stem}_raw.wav"
        final_wav = _output_wav_path(ctx)

        loudnorm_mode = "none"

        # 1a. ffmpeg: 任意形式 → 16kHz mono WAV（+ 任意 loudnorm）
        if two_pass:
            # 1-pass (analysis only): measured_* を取得
            analysis_args = [
                "ffmpeg", "-y", "-i", str(ctx.input_path),
                "-af", f"loudnorm={loudnorm}:print_format=json",
                "-f", "null", "-",
            ]
            rc, _out, err = _run_ffmpeg_capture(analysis_args)
            measured = _parse_loudnorm_measured(err) if rc == 0 else None
            if measured:
                af_spec = _build_two_pass_loudnorm_filter(loudnorm, measured)
                _run_ffmpeg([
                    "ffmpeg", "-y", "-i", str(ctx.input_path),
                    "-ac", "1", "-ar", str(sr),
                    "-af", af_spec,
                    str(raw_wav),
                ])
                loudnorm_mode = "two_pass"
            else:
                logger.warning("2-pass loudnorm analysis failed; falling back to 1-pass")
                _run_ffmpeg([
                    "ffmpeg", "-y", "-i", str(ctx.input_path),
                    "-ac", "1", "-ar", str(sr),
                    "-af", f"loudnorm={loudnorm}",
                    str(raw_wav),
                ])
                loudnorm_mode = "one_pass_fallback"
        else:
            ffmpeg_args = ["ffmpeg", "-y", "-i", str(ctx.input_path), "-ac", "1", "-ar", str(sr)]
            if loudnorm:
                ffmpeg_args += ["-af", f"loudnorm={loudnorm}"]
                loudnorm_mode = "one_pass"
            ffmpeg_args += [str(raw_wav)]
            _run_ffmpeg(ffmpeg_args)

        # 2. noisereduce でノイズ除去（CPU、遅延 import）
        try:
            import numpy as np
            import noisereduce as nr
            import soundfile as sf

            data, rate = sf.read(str(raw_wav))
            if data.ndim > 1:
                data = data.mean(axis=1)
            reduced = nr.reduce_noise(y=data, sr=rate, prop_decrease=strength)
            sf.write(str(final_wav), reduced.astype(np.float32), rate)
        except Exception as e:
            logger.warning("noisereduce failed (%s); falling back to raw wav.", e)
            shutil.copy(raw_wav, final_wav)
        finally:
            raw_wav.unlink(missing_ok=True)

        ctx.audio_path = final_wav
        duration = self._probe_duration(final_wav)
        ctx.meta.setdefault("preprocess", {}).update(
            {
                "provider": self.provider,
                "sample_rate": sr,
                "duration_sec": duration,
                "denoise_strength": strength,
                "loudnorm_mode": loudnorm_mode,
                "output_path": str(final_wav),
            }
        )
        ctx.record_timing("preprocess", time.monotonic() - t0)
        logger.info("[1/N] preprocess: %s → %s (%.1fs, loudnorm=%s)", ctx.input_path.name, final_wav.name, duration, loudnorm_mode)
        return ctx

    @staticmethod
    def _probe_duration(wav: Path) -> float:
        try:
            import soundfile as sf
            info = sf.info(str(wav))
            return float(info.frames) / float(info.samplerate or 1)
        except Exception:
            return 0.0


@Step.register("preprocess", "simple")
class SimplePreprocessStep(Step):
    """ffmpeg 単独で loudnorm 正規化（軽量、seminar 向け）。

    params:
      target_sr (int, default 16000)
      loudnorm (str, default "I=-16:TP=-1.5:LRA=11")
      denoise (bool, default False): ffmpeg afftdn フィルタを追加
    """

    default_provider = "simple"

    _LOUDNORM_DEFAULT = "I=-16:TP=-1.5:LRA=11"
    _DENOISE_CHAIN = "highpass=f=80,lowpass=f=8000,afftdn=nf=-25"

    def process(self, ctx: Context) -> Context:
        _check_ffmpeg()
        t0 = time.monotonic()

        sr: int = int(self.params.get("target_sr", 16000))
        loudnorm: str = self.params.get("loudnorm", self._LOUDNORM_DEFAULT)
        denoise: bool = bool(self.params.get("denoise", False))

        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        final_wav = _output_wav_path(ctx)

        af = f"loudnorm={loudnorm}"
        if denoise:
            af = f"{self._DENOISE_CHAIN},{af}"

        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-i", str(ctx.input_path),
                "-ac", "1", "-ar", str(sr),
                "-af", af,
                str(final_wav),
            ]
        )

        ctx.audio_path = final_wav
        duration = DefaultPreprocessStep._probe_duration(final_wav)
        ctx.meta.setdefault("preprocess", {}).update(
            {
                "provider": self.provider,
                "sample_rate": sr,
                "duration_sec": duration,
                "loudnorm": loudnorm,
                "denoise": denoise,
                "output_path": str(final_wav),
            }
        )
        ctx.record_timing("preprocess", time.monotonic() - t0)
        logger.info("[1/N] preprocess (simple): %s → %s (%.1fs)", ctx.input_path.name, final_wav.name, duration)
        return ctx
