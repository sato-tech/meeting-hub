"""NeMo vs pyannote のベンチマーク骨子。

Phase 4 完了条件:
  - 評価スクリプトが動く状態にする（pyannote は実行、NeMo は provider 追加と同時にスイッチ）
  - DER（Diarization Error Rate）を共通指標とする
  - 実データは利用者が用意（WAV + RTTM 形式の ground truth）

本ファイルは**骨子のみ**。NeMo の導入は依存を追加せず、実測時に pip install を行う前提。
Phase 4 の ROADMAP 要件「NeMo の評価結果に基づき pyannote 継続 or 切替を決定」を支える。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiarizeBenchmarkResult:
    provider: str
    der: float                      # 0.0〜1.0、小さいほど良い
    total_duration_sec: float
    num_speakers_detected: int
    elapsed_sec: float
    extra: dict[str, Any]


def compute_der(
    hypothesis_segments: list[dict[str, Any]],
    reference_segments: list[dict[str, Any]],
    *,
    collar_sec: float = 0.25,
) -> float:
    """DER（簡易版）を計算する。

    精密な DER は pyannote.metrics などに任せるべきだが、依存を減らすため
    Phase 4 では「マッチしたフレーム比率」で近似する骨子実装を提供する。

    Args:
      hypothesis_segments: 予測 [{start, end, speaker}]
      reference_segments: ground truth 同様
      collar_sec: 境界付近の許容幅（無視される）

    Returns:
      DER [0, 1]。境界は hypothesis の end が最大の segment までを対象とする。
    """
    if not reference_segments:
        return 1.0 if hypothesis_segments else 0.0
    if not hypothesis_segments:
        return 1.0

    # 分解能 0.1 秒でフレーム化
    step = 0.1
    total_end = max(float(s["end"]) for s in reference_segments)
    frames = int(total_end / step)

    def assign(segments, frames, step) -> list[str]:
        out = ["-"] * frames
        for s in segments:
            si = int(float(s["start"]) / step)
            ei = min(int(float(s["end"]) / step), frames)
            for i in range(max(si, 0), ei):
                out[i] = str(s.get("speaker", "?"))
        return out

    ref_labels = assign(reference_segments, frames, step)
    hyp_labels = assign(hypothesis_segments, frames, step)

    # speaker ラベル間の最適マッピング（Hungarian の簡易版: 頻度最大一致）
    # pyannote/NeMo のラベル名は違うため、ここで合わせる
    pairs: dict[tuple[str, str], int] = {}
    for r, h in zip(ref_labels, hyp_labels):
        if r == "-" or h == "-":
            continue
        pairs[(r, h)] = pairs.get((r, h), 0) + 1

    # ref label ごとに最も頻度の高い hyp label を採用
    ref_to_hyp: dict[str, str] = {}
    for (r, h), cnt in sorted(pairs.items(), key=lambda x: -x[1]):
        if r not in ref_to_hyp and h not in ref_to_hyp.values():
            ref_to_hyp[r] = h

    matched = 0
    counted = 0
    for r, h in zip(ref_labels, hyp_labels):
        if r == "-":
            continue
        counted += 1
        if ref_to_hyp.get(r) == h:
            matched += 1

    if counted == 0:
        return 1.0
    # collar 考慮は簡略化
    der = 1.0 - matched / counted
    return max(0.0, min(1.0, der))


def run_benchmark(
    wav_path: Path,
    reference_rttm: Path | None,
    providers: list[str] | None = None,
    *,
    params: dict[str, Any] | None = None,
) -> list[DiarizeBenchmarkResult]:
    """provider 群に対して diarize を走らせ、DER を比較する。

    Args:
      wav_path: 音声
      reference_rttm: ground truth（RTTM 形式、None なら DER は 1.0 固定）
      providers: ["pyannote", "nemo"] などの名前リスト
      params: 各 provider に渡す params

    Returns:
      DiarizeBenchmarkResult のリスト。provider 順。
    """
    providers = providers or ["pyannote"]
    params = params or {}

    reference = _load_rttm(reference_rttm) if reference_rttm and reference_rttm.exists() else []

    results: list[DiarizeBenchmarkResult] = []
    for prov in providers:
        try:
            segs, elapsed, extra = _run_single(prov, wav_path, params)
        except Exception as e:
            logger.exception("benchmark provider=%s failed: %s", prov, e)
            continue

        der = compute_der(segs, reference) if reference else 1.0
        num_sp = len({s["speaker"] for s in segs}) if segs else 0
        results.append(
            DiarizeBenchmarkResult(
                provider=prov,
                der=der,
                total_duration_sec=max((float(s["end"]) for s in segs), default=0.0),
                num_speakers_detected=num_sp,
                elapsed_sec=elapsed,
                extra=extra,
            )
        )
    return results


def _run_single(provider: str, wav_path: Path, params: dict[str, Any]):
    """指定 provider を呼び出し、segments + elapsed + extra を返す。"""
    import time

    t0 = time.monotonic()
    if provider == "pyannote":
        return _run_pyannote(wav_path, params), time.monotonic() - t0, {}
    if provider == "nemo":
        return _run_nemo(wav_path, params), time.monotonic() - t0, {"note": "skeleton"}
    raise ValueError(f"Unknown provider: {provider}")


def _run_pyannote(wav_path: Path, params: dict[str, Any]) -> list[dict[str, Any]]:
    import os
    from pyannote.audio import Pipeline  # type: ignore[import-not-found]

    token = os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise EnvironmentError("HUGGINGFACE_TOKEN is required for pyannote")
    model = params.get("model", "pyannote/speaker-diarization-3.1")
    pipeline = Pipeline.from_pretrained(model, use_auth_token=token)
    kwargs = {}
    if params.get("num_speakers"):
        kwargs["num_speakers"] = int(params["num_speakers"])
    else:
        kwargs["min_speakers"] = int(params.get("min_speakers", 2))
        kwargs["max_speakers"] = int(params.get("max_speakers", 4))
    diarization = pipeline(str(wav_path), **kwargs)
    segs = []
    for turn, _track, spk in diarization.itertracks(yield_label=True):
        segs.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(spk)})
    return segs


def _run_nemo(wav_path: Path, params: dict[str, Any]) -> list[dict[str, Any]]:
    """NeMo 実行スケルトン。

    本 Phase では NeMo を requirements に含めない（実測時に pip install nemo_toolkit）。
    呼び出された時点で import が失敗すれば skeleton として warning を返す。
    """
    try:
        from nemo.collections.asr.models.msdd_models import NeuralDiarizer  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError(
            "NeMo not installed. `pip install nemo_toolkit[asr]` to enable benchmarking."
        )
    # 本実装は利用者側で NeMo を入れたあと、ここに MSDD 呼び出しを書く
    raise NotImplementedError(
        "NeMo benchmarking is a skeleton. Wire up the actual MSDD invocation locally."
    )


def emit_decision_report(
    results: list[DiarizeBenchmarkResult],
    *,
    output_path: Path | None = None,
    der_threshold: float = 0.05,
    speed_threshold_ratio: float = 0.7,
) -> str:
    """ベンチマーク結果から「継続 vs 切替」の意思決定 Markdown を生成する。

    判定ロジック:
      - pyannote が既定、NeMo を候補とする
      - 全 provider の結果を表化
      - NeMo が pyannote に対し **DER ≤ pyannote_DER - der_threshold**
        かつ **elapsed ≤ pyannote_elapsed * (1 + speed_threshold_ratio)** なら **切替推奨**
      - そうでなければ **pyannote 継続推奨**

    Args:
      results: `run_benchmark` の戻り値
      output_path: 指定時は Markdown をファイルに書き出す
      der_threshold: NeMo 採用条件の DER 改善量（既定 5%）
      speed_threshold_ratio: 許容する処理時間の増分比率（既定 70%）

    Returns:
      Markdown 文字列
    """
    by_prov = {r.provider: r for r in results}
    pyannote = by_prov.get("pyannote")
    nemo = by_prov.get("nemo")

    lines: list[str] = []
    lines.append("# Diarization Benchmark Decision Report")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| provider | DER | speakers_detected | elapsed_sec | total_duration_sec |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r.provider} | {r.der:.3f} | {r.num_speakers_detected} | "
            f"{r.elapsed_sec:.1f} | {r.total_duration_sec:.1f} |"
        )
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    if pyannote is None:
        lines.append("- pyannote の結果がないため判断不能。pyannote を追加してから再実行してください。")
    elif nemo is None:
        lines.append(
            "- NeMo の結果がないため、**pyannote 継続を推奨**します。"
            "NeMo を評価する場合は `pip install nemo_toolkit[asr]` 後に `_run_nemo` を実装して再実行してください。"
        )
    else:
        der_delta = pyannote.der - nemo.der
        time_ratio = (nemo.elapsed_sec / pyannote.elapsed_sec) if pyannote.elapsed_sec > 0 else float("inf")
        lines.append(f"- DER 改善量（pyannote → nemo）: **{der_delta:+.3f}** （閾値: ≥ {der_threshold}）")
        lines.append(
            f"- 処理時間比（nemo / pyannote）: **{time_ratio:.2f}×** （閾値: ≤ {1 + speed_threshold_ratio:.2f}×）"
        )
        if der_delta >= der_threshold and time_ratio <= (1 + speed_threshold_ratio):
            lines.append("")
            lines.append("### ✅ **NeMo 切替推奨**")
            lines.append(
                "NeMo が DER・速度ともに基準を満たします。`core/steps/diarize.py` に "
                "`@Step.register('diarize', 'nemo')` の本実装を追加し、カセットで切替可能にしてください。"
            )
        else:
            lines.append("")
            lines.append("### ✅ **pyannote 継続を推奨**")
            if der_delta < der_threshold:
                lines.append(f"- DER 改善量 {der_delta:.3f} が基準 {der_threshold} 未満")
            if time_ratio > (1 + speed_threshold_ratio):
                lines.append(f"- 処理時間比 {time_ratio:.2f}× が基準 {1 + speed_threshold_ratio:.2f}× 超過")
    lines.append("")
    lines.append(f"※ 閾値は `der_threshold={der_threshold}`, `speed_threshold_ratio={speed_threshold_ratio}` で計算。")

    md = "\n".join(lines)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(md, encoding="utf-8")
    return md


def _load_rttm(path: Path) -> list[dict[str, Any]]:
    """RTTM 形式の ground truth を [{start, end, speaker}] に変換。"""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        # SPEAKER <file> 1 <start> <dur> <NA> <NA> <spk> <NA> <NA>
        if len(fields) < 9 or fields[0] != "SPEAKER":
            continue
        start = float(fields[3])
        dur = float(fields[4])
        spk = fields[7]
        out.append({"start": start, "end": start + dur, "speaker": spk})
    return out
