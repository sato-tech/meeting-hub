"""diarize Step — 話者分離。

Provider:
  - pyannote:       pyannote.audio Pipeline による話者分離（Phase 1）
  - channel_based:  2ch ライブ録音で Ch1=self / Ch2=other を機械的に割当（Phase 2）
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.steps.base import Step

logger = logging.getLogger(__name__)


@Step.register("diarize", "pyannote")
class PyannoteDiarizeStep(Step):
    """pyannote/speaker-diarization-3.1 による話者分離。

    params:
      model (str, default "pyannote/speaker-diarization-3.1")
      num_speakers (int | None): 固定指定
      min_speakers (int, default 2)
      max_speakers (int, default 4)
      speaker_names (dict[str, str], optional): SPEAKER_00 → 表示名
      segmentation_threshold (float, default 0.4)
      clustering_threshold (float, default 0.65)
      min_cluster_size (int, default 15)
      use_whisperx_align (bool, default True): 単語レベル timestamp で境界精度を上げる
    """

    default_provider = "pyannote"

    def __init__(self, provider: str | None, params: dict[str, Any]):
        super().__init__(provider, params)
        self._pipeline = None

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        from pyannote.audio import Pipeline  # 遅延 import

        model = self.params.get("model", "pyannote/speaker-diarization-3.1")
        token = os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            raise EnvironmentError(
                "HUGGINGFACE_TOKEN is not set. Required for pyannote diarization."
            )
        logger.info("Loading pyannote pipeline: %s", model)
        self._pipeline = Pipeline.from_pretrained(model, use_auth_token=token)

        # P4: pyannote のハイパーパラメータをカセット params から反映
        self._instantiate_hyperparams(self._pipeline)
        return self._pipeline

    def _instantiate_hyperparams(self, pipeline) -> None:
        """カセット params から pyannote のハイパーパラメータを `instantiate()` で上書き。

        反映対象:
          - segmentation.threshold (default 0.4)
          - segmentation.min_duration_on (default 0.0)  ← 短発話を逃さない
          - segmentation.min_duration_off (default 0.0)
          - clustering.threshold (default 0.7)
          - clustering.method (default "centroid")
          - clustering.min_cluster_size (default 12)

        いずれもカセット params に明示があるときのみ反映。pyannote 3.1 の `instantiate`
        API は dict-of-dict を受け取る。失敗してもパイプラインは default 設定で動くよう
        warning を出して継続する。
        """
        seg_keys = ("segmentation_threshold", "min_duration_on", "min_duration_off")
        clu_keys = ("clustering_threshold", "clustering_method", "min_cluster_size")
        if not any(k in self.params for k in seg_keys + clu_keys):
            return  # 何も指定がなければ pyannote の既定値を使う

        seg_cfg: dict[str, Any] = {}
        if "segmentation_threshold" in self.params:
            seg_cfg["threshold"] = float(self.params["segmentation_threshold"])
        if "min_duration_on" in self.params:
            seg_cfg["min_duration_on"] = float(self.params["min_duration_on"])
        if "min_duration_off" in self.params:
            seg_cfg["min_duration_off"] = float(self.params["min_duration_off"])

        clu_cfg: dict[str, Any] = {}
        if "clustering_threshold" in self.params:
            clu_cfg["threshold"] = float(self.params["clustering_threshold"])
        if "clustering_method" in self.params:
            clu_cfg["method"] = str(self.params["clustering_method"])
        if "min_cluster_size" in self.params:
            clu_cfg["min_cluster_size"] = int(self.params["min_cluster_size"])

        hyper: dict[str, dict[str, Any]] = {}
        if seg_cfg:
            hyper["segmentation"] = seg_cfg
        if clu_cfg:
            hyper["clustering"] = clu_cfg

        try:
            pipeline.instantiate(hyper)
            logger.info("pyannote hyperparams instantiated: %s", hyper)
        except Exception as e:
            logger.warning(
                "pyannote.instantiate(%s) failed (%s); falling back to default hyperparams",
                hyper, e,
            )

    def _apply_to_segments(
        self,
        segments: list[dict[str, Any]],
        diarization,
        speaker_names: dict[str, str],
    ) -> list[dict[str, Any]]:
        """セグメントの中央時刻に被る speaker ラベルを割り当てる（粗い方法）。"""
        labeled: list[dict[str, Any]] = []
        for seg in segments:
            mid = (float(seg["start"]) + float(seg["end"])) / 2
            label = "UNKNOWN"
            for turn, _track, spk in diarization.itertracks(yield_label=True):
                if turn.start <= mid <= turn.end:
                    label = str(spk)
                    break
            display = speaker_names.get(label, label)
            out = dict(seg)
            out["speaker"] = display
            labeled.append(out)
        return labeled

    def _apply_with_whisperx_align(
        self,
        audio_path: Path,
        segments: list[dict[str, Any]],
        diarization,
        speaker_names: dict[str, str],
        language: str,
    ) -> list[dict[str, Any]]:
        """WhisperX align + assign_word_speakers で精密な境界の speaker 割当を得る。

        失敗時（whisperx 未 install / align model ロード失敗）は ValueError を投げ、
        呼び出し側でフォールバックする。
        """
        import whisperx  # type: ignore[import-not-found]

        # whisperx align は segments を list[dict{start,end,text}] で受け取り、
        # audio は 16kHz mono ndarray を期待する
        audio = whisperx.load_audio(str(audio_path))
        align_segments = [
            {"start": float(s["start"]), "end": float(s["end"]), "text": s.get("text", "")}
            for s in segments
        ]
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cpu")
        aligned = whisperx.align(align_segments, align_model, metadata, audio, device="cpu")
        # diarization を DataFrame 形式に変換（whisperx が期待する形）
        result = whisperx.assign_word_speakers(diarization, aligned)

        # result["segments"] に speaker が割当済みで返る想定
        result_segments = result.get("segments") if isinstance(result, dict) else None
        if not result_segments:
            raise ValueError("whisperx.assign_word_speakers returned no segments")

        # P5: word 単位で speaker が異なる場合は segment を分割する
        split_on_change = bool(self.params.get("split_on_speaker_change", True))

        labeled: list[dict[str, Any]] = []
        for orig, r in zip(segments, result_segments):
            words = r.get("words") or []
            if split_on_change and len(words) >= 2:
                # word ごとの speaker を集計
                speakers_seen = {
                    str(w.get("speaker")) for w in words if w.get("speaker")
                }
                if len(speakers_seen) >= 2:
                    sub_segments = self._split_segment_by_word_speakers(
                        orig, words, speaker_names
                    )
                    labeled.extend(sub_segments)
                    continue

            label = str(r.get("speaker") or "UNKNOWN")
            out = dict(orig)
            out["speaker"] = speaker_names.get(label, label)
            labeled.append(out)
        return labeled

    @staticmethod
    def _split_segment_by_word_speakers(
        orig: dict[str, Any],
        words: list[dict[str, Any]],
        speaker_names: dict[str, str],
    ) -> list[dict[str, Any]]:
        """1 segment 内で word ごとに speaker が変わる場合、speaker 連続区間で分割。

        例: words=[A, A, B, B, A] の場合、3 つの sub-segment に分かれる。
        speaker 不明な word（speaker キーなし）は直前の speaker を継承。

        text は word.word を結合、start/end は word.start/word.end の min/max。
        timestamps が word に無い場合は orig の start/end を均等分割で近似。
        """
        if not words:
            return [dict(orig)]

        orig_start = float(orig["start"])
        orig_end = float(orig["end"])

        # speaker 連続区間に分割
        groups: list[dict[str, Any]] = []
        current_speaker: str | None = None
        current_words: list[dict[str, Any]] = []

        last_speaker = "UNKNOWN"
        for w in words:
            spk = w.get("speaker")
            if spk:
                last_speaker = str(spk)
            else:
                spk = last_speaker

            if current_speaker is None:
                current_speaker = spk
                current_words = [w]
            elif spk == current_speaker:
                current_words.append(w)
            else:
                groups.append({"speaker": current_speaker, "words": current_words})
                current_speaker = spk
                current_words = [w]

        if current_words:
            groups.append({"speaker": current_speaker, "words": current_words})

        # 各 group を sub-segment に変換
        out: list[dict[str, Any]] = []
        n = len(groups)
        for i, g in enumerate(groups):
            ws = g["words"]
            # word.start/end が取れれば使う、無ければ orig を均等分割
            starts = [float(w["start"]) for w in ws if "start" in w and w["start"] is not None]
            ends = [float(w["end"]) for w in ws if "end" in w and w["end"] is not None]
            if starts and ends:
                seg_start = min(starts)
                seg_end = max(ends)
            else:
                # フォールバック：orig を均等分割
                seg_start = orig_start + (orig_end - orig_start) * i / max(n, 1)
                seg_end = orig_start + (orig_end - orig_start) * (i + 1) / max(n, 1)

            text = "".join(str(w.get("word", "")) for w in ws).strip()
            speaker_label = speaker_names.get(g["speaker"], g["speaker"])
            out.append({
                **{k: v for k, v in orig.items() if k not in ("start", "end", "text", "speaker")},
                "start": seg_start,
                "end": seg_end,
                "text": text or orig.get("text", ""),
                "speaker": speaker_label,
            })
        return out

    def process(self, ctx: Context) -> Context:
        if not ctx.audio_path or not ctx.segments:
            raise RuntimeError("diarize Step requires ctx.audio_path and ctx.segments")

        t0 = time.monotonic()
        pipeline = self._load_pipeline()

        num_speakers = self.params.get("num_speakers")
        kwargs: dict[str, Any] = {}
        if num_speakers:
            kwargs["num_speakers"] = int(num_speakers)
        else:
            kwargs["min_speakers"] = int(self.params.get("min_speakers", 2))
            kwargs["max_speakers"] = int(self.params.get("max_speakers", 4))

        logger.info("Diarizing %s (%s)", ctx.audio_path.name, kwargs)
        diarization = pipeline(str(ctx.audio_path), **kwargs)

        speaker_names = self.params.get("speaker_names") or {}
        use_align = bool(self.params.get("use_whisperx_align", True))
        align_language = str(self.params.get("align_language", "ja"))

        labeled = None
        align_mode = "coarse"
        if use_align:
            try:
                labeled = self._apply_with_whisperx_align(
                    ctx.audio_path, ctx.segments, diarization, speaker_names, align_language
                )
                align_mode = "whisperx_align"
            except Exception as e:
                logger.warning(
                    "whisperx align unavailable (%s); falling back to coarse midpoint assignment",
                    e,
                )
                ctx.add_warning(f"diarize:whisperx_fallback:{type(e).__name__}")

        if labeled is None:
            labeled = self._apply_to_segments(ctx.segments, diarization, speaker_names)

        ctx.segments = labeled

        dist: dict[str, float] = {}
        for s in ctx.segments:
            dist[s["speaker"]] = dist.get(s["speaker"], 0.0) + (s["end"] - s["start"])
        ctx.meta.setdefault("diarize", {}).update(
            {
                "provider": self.provider,
                "num_speakers_detected": len(dist),
                "speaker_time_distribution": dist,
                "align_mode": align_mode,
            }
        )
        ctx.record_timing("diarize", time.monotonic() - t0)
        logger.info("[3/N] diarize: %d speakers detected (align=%s)", len(dist), align_mode)
        return ctx


@Step.register("diarize", "channel_based")
class ChannelBasedDiarizeStep(Step):
    """2ch 録音を前提に、チャネルから機械的に話者を割当。

    live_audio で `mix: separate` で 2ch 保存した場合に使用。Ch1=self, Ch2=other を割る。
    ファイル入力でも 2ch WAV なら使用可能。

    params:
      speaker_names (dict[str, str], optional):
        例: {ch0: self, ch1: other} → {"ch0": "マネージャ", "ch1": "メンバー"}
      dominant_threshold (float, default 0.6):
        セグメント内で音量が大きい方の ch を採用する閾値（比率）
    """

    default_provider = "channel_based"

    def process(self, ctx: Context) -> Context:
        if not ctx.audio_path or not ctx.segments:
            raise RuntimeError("channel_based diarize requires ctx.audio_path and ctx.segments")

        t0 = time.monotonic()

        import numpy as np
        import soundfile as sf

        data, sr = sf.read(str(ctx.audio_path))
        if data.ndim != 2 or data.shape[1] < 2:
            logger.warning(
                "channel_based diarize: audio is not 2ch (shape=%s). Falling back to ch0=unknown.",
                getattr(data, "shape", None),
            )
            # 1ch なら全部 UNKNOWN のまま返す
            for s in ctx.segments:
                s["speaker"] = s.get("speaker") or "UNKNOWN"
            ctx.record_timing("diarize", time.monotonic() - t0)
            return ctx

        speaker_names = self.params.get("speaker_names") or {}
        names = {
            0: speaker_names.get("ch0", "self"),
            1: speaker_names.get("ch1", "other"),
        }
        threshold = float(self.params.get("dominant_threshold", 0.6))

        dist: dict[str, float] = {}
        for seg in ctx.segments:
            start_f = int(float(seg["start"]) * sr)
            end_f = int(float(seg["end"]) * sr)
            window = data[start_f:end_f]
            if window.size == 0:
                seg["speaker"] = names[0]
                continue
            ch0_rms = float(np.sqrt(np.mean(window[:, 0] ** 2))) if window.shape[0] > 0 else 0.0
            ch1_rms = float(np.sqrt(np.mean(window[:, 1] ** 2))) if window.shape[0] > 0 else 0.0
            total = ch0_rms + ch1_rms + 1e-9
            ratio0 = ch0_rms / total
            if ratio0 >= threshold:
                label = names[0]
            elif ratio0 <= (1 - threshold):
                label = names[1]
            else:
                # 両方鳴っているときは大きい方を採用
                label = names[0] if ch0_rms >= ch1_rms else names[1]
            seg["speaker"] = label
            dist[label] = dist.get(label, 0.0) + (float(seg["end"]) - float(seg["start"]))

        ctx.meta.setdefault("diarize", {}).update(
            {
                "provider": self.provider,
                "num_speakers_detected": len(dist),
                "speaker_time_distribution": dist,
            }
        )
        ctx.record_timing("diarize", time.monotonic() - t0)
        logger.info("[3/N] diarize (channel_based): %s", list(dist.keys()))
        return ctx
