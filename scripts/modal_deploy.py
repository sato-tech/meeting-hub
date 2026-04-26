"""Modal deploy スクリプト。

使い方:
  modal deploy scripts/modal_deploy.py

事前準備:
  1. `pip install modal`
  2. `modal token new`（ブラウザで認証）
  3. `modal secret create meeting-hub-secrets HUGGINGFACE_TOKEN=... ANTHROPIC_API_KEY=...`
  4. `modal deploy scripts/modal_deploy.py`

Modal 無料枠（Starter）$30/月 以内で運用可能な想定（REPORT_PHASE3_PLAN.md §1）。

※ 実モデル（faster-whisper / pyannote）を動かすため初回実行は GPU 取得が必要。
   開発中は local 実行でテストし、Modal 側は deploy 後に cassette の `runtime: modal` で切替。
"""
from __future__ import annotations

try:
    import modal
except ImportError:  # pragma: no cover
    raise SystemExit(
        "modal SDK not installed. `pip install modal` then `modal token new`."
    )


APP_NAME = "meeting-hub"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "faster-whisper>=1.1.0",
        "whisperx>=3.1.0",
        "pyannote.audio>=3.1.0",
        "torch>=2.0.0",
        "torchaudio>=2.0.0",
        "soundfile>=0.12.0",
        "numpy",
    )
)

secrets = [modal.Secret.from_name("meeting-hub-secrets")]

app = modal.App(APP_NAME, image=image, secrets=secrets)


@app.function(gpu="A10G", timeout=1800, memory=8192)
def transcribe_on_modal(
    audio_bytes: bytes,
    segments: list,
    params: dict,
    provider: str,
) -> dict:
    """faster-whisper で transcribe。GPU float16。"""
    import os
    import tempfile
    from pathlib import Path
    from faster_whisper import WhisperModel

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        wav_path = f.name

    model_name = params.get("model", "large-v3")
    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    segs_iter, _info = model.transcribe(
        wav_path,
        language=params.get("language", "ja"),
        beam_size=int(params.get("beam_size", 5)),
        vad_filter=bool(params.get("vad_filter", True)),
        no_speech_threshold=float(params.get("no_speech_threshold", 0.6)),
        condition_on_previous_text=bool(params.get("condition_on_previous_text", False)),
        word_timestamps=True,
    )
    result_segments = [
        {"start": float(s.start), "end": float(s.end), "text": (s.text or "").strip(), "speaker": "未割当"}
        for s in segs_iter
    ]
    Path(wav_path).unlink(missing_ok=True)
    return {
        "segments": result_segments,
        "meta": {"provider": provider, "model": model_name, "runtime": "modal", "device": "cuda"},
    }


@app.function(gpu="A10G", timeout=1800, memory=8192)
def diarize_on_modal(
    audio_bytes: bytes,
    segments: list,
    params: dict,
    provider: str,
) -> dict:
    """pyannote で話者分離（A10G GPU）。"""
    import os
    import tempfile
    from pathlib import Path
    from pyannote.audio import Pipeline

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        wav_path = f.name

    token = os.environ["HUGGINGFACE_TOKEN"]
    model = params.get("model", "pyannote/speaker-diarization-3.1")
    pipeline = Pipeline.from_pretrained(model, use_auth_token=token)
    pipeline.to("cuda")

    kwargs = {}
    if params.get("num_speakers"):
        kwargs["num_speakers"] = int(params["num_speakers"])
    else:
        kwargs["min_speakers"] = int(params.get("min_speakers", 2))
        kwargs["max_speakers"] = int(params.get("max_speakers", 4))

    diarization = pipeline(wav_path, **kwargs)
    speaker_names = params.get("speaker_names") or {}

    labeled = []
    for seg in segments:
        mid = (float(seg["start"]) + float(seg["end"])) / 2
        label = "UNKNOWN"
        for turn, _track, spk in diarization.itertracks(yield_label=True):
            if turn.start <= mid <= turn.end:
                label = str(spk)
                break
        out = dict(seg)
        out["speaker"] = speaker_names.get(label, label)
        labeled.append(out)

    Path(wav_path).unlink(missing_ok=True)
    return {"segments": labeled, "meta": {"provider": provider, "runtime": "modal", "device": "cuda"}}
