"""カセットロード + override 適用 + ライブプロファイル変換。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from core.cassette_schema import CassetteConfig

logger = logging.getLogger(__name__)

_CASSETTE_ROOT = Path(__file__).resolve().parents[1] / "cassettes"


# ─── 旧ライブ専用カセット名 → 会議タイプカセット + live フラグへのマッピング ──
_DEPRECATED_LIVE_NAMES = {
    "live_sales": "sales_meeting",
    "live_internal": "internal_meeting",
    "one_on_one_live": "one_on_one",
}


def resolve_cassette_path(name_or_path: str) -> Path:
    """カセット名またはパスから YAML パスを解決。

    - `.yaml` / `.yml` を含むか、`/` を含めばそのままパス扱い
    - それ以外は `cassettes/{name}.yaml`
    """
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml") or "/" in name_or_path or p.is_absolute():
        return p.expanduser().resolve()
    candidate = _CASSETTE_ROOT / f"{name_or_path}.yaml"
    return candidate


def load_cassette(
    name_or_path: str,
    overrides: list[str] | None = None,
    *,
    live: bool = False,
) -> CassetteConfig:
    """カセットをロードして、必要ならライブ変換 + 上書きを適用。

    Args:
      name_or_path: カセット名 or YAML パス
      overrides: `["KEY=VAL", ...]` 形式の上書き
      live: True ならライブプロファイル（chunked transcribe + channel_based diarize 等）を適用
    """
    effective_live = live
    # 旧 live_* 系カセット名 → 新カセット + live=True に自動マッピング（警告付き）
    if name_or_path in _DEPRECATED_LIVE_NAMES:
        new_name = _DEPRECATED_LIVE_NAMES[name_or_path]
        logger.warning(
            "cassette name %r is deprecated; use %r with --live (or live:// URI) instead",
            name_or_path, new_name,
        )
        name_or_path = new_name
        effective_live = True

    path = resolve_cassette_path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"Cassette not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ライブ変換はユーザーの override より前に適用（override で上書き可能）
    if effective_live:
        apply_live_profile(data)

    if overrides:
        for ov in overrides:
            _apply_override(data, ov)

    return CassetteConfig.model_validate(data)


# ═══════════════════════════════════════════════════
# ライブプロファイル
# ═══════════════════════════════════════════════════
_LIVE_DEFAULT_CHANNELS = [
    {"source": "microphone", "label": "self"},
    {"source": "system_output", "label": "other"},
]


def apply_live_profile(data: dict[str, Any]) -> None:
    """カセット YAML dict をライブ用に in-place 変換。

    変換内容（カセット側で明示されていれば尊重、未指定のみ既定値を当てる箇所と、
    ライブの本質的な要件として上書きする箇所の二種類がある）:

    **上書き（ライブ本質）**:
      - input.type = live_audio
      - preprocess.provider = simple
      - transcribe.provider = faster_whisper_chunked
      - transcribe.params.model = large-v3-turbo  （速度優先）
      - diarize.provider = channel_based  （2ch キャプチャ前提）
      - llm.batch_mode = False             （即時性重視）

    **setdefault（明示があれば残す）**:
      - input.storage, input.channels, input.mix
      - preprocess.params.loudnorm
      - transcribe.params.chunk_sec / overlap_sec
      - diarize.params.speaker_names.ch0/ch1 / dominant_threshold

    **マッピング**:
      - diarize の pyannote 用 SPEAKER_00/SPEAKER_01 名があれば ch0/ch1 に引継ぎ
    """
    # ─ input ─
    input_cfg = data.setdefault("input", {})
    input_cfg["type"] = "live_audio"
    input_cfg.setdefault("storage", "local")
    input_cfg.setdefault("channels", list(_LIVE_DEFAULT_CHANNELS))
    input_cfg.setdefault("mix", "separate")

    # ─ llm ─
    llm_cfg = data.setdefault("llm", {})
    llm_cfg["batch_mode"] = False

    # ─ pipeline ─
    pipeline = data.get("pipeline") or []
    for step in pipeline:
        sname = step.get("step")
        if sname == "preprocess":
            step["provider"] = "simple"
            params = step.setdefault("params", {})
            params.setdefault("loudnorm", "I=-16:TP=-1.5:LRA=11")
        elif sname == "transcribe":
            step["provider"] = "faster_whisper_chunked"
            params = step.setdefault("params", {})
            params["model"] = "large-v3-turbo"
            params.setdefault("chunk_sec", 20.0)
            params.setdefault("overlap_sec", 2.0)
            # 短発話対応（P2）：ライブの短ターン会話で同一 segment 化を防ぐ
            params.setdefault("merge_gap_sec", 0.3)
            # 短発話対応（P1）：ライブでも相槌を取りこぼさない
            params.setdefault("vad_min_silence_ms", 100)
            params.setdefault("vad_speech_pad_ms", 100)
            params.setdefault("min_text_length", 1)
        elif sname == "diarize":
            if not step.get("enabled", True):
                continue
            step["provider"] = "channel_based"
            params = step.setdefault("params", {})
            # pyannote 用の speaker_names があれば ch0/ch1 にマッピング
            old_names = params.get("speaker_names") or {}
            params["speaker_names"] = {
                "ch0": old_names.get("ch0") or old_names.get("SPEAKER_00") or "self",
                "ch1": old_names.get("ch1") or old_names.get("SPEAKER_01") or "other",
            }
            # 短発話対応（P3）：マイク漏れ込みでも相槌を判定できるよう少し緩める
            params.setdefault("dominant_threshold", 0.55)
            # pyannote 専用パラメータは残っていても無害（channel_based では無視される）


_STEP_NAMES = frozenset(
    {"preprocess", "transcribe", "diarize", "term_correct", "llm_cleanup", "minutes_extract", "format"}
)


def _apply_override(data: dict[str, Any], expr: str) -> None:
    """`KEY=VAL` 形式で dict を in-place 上書き。

    キー記法:
      - `transcribe.params.beam_size=3` — 先頭がステップ名なら pipeline 内を探索
      - `llm_cleanup.enabled=false` — ステップ有効/無効
      - `llm.batch_mode=false` — トップレベルのサブキー
      - `pipeline[1].params.model=large-v3` — 添字指定

    数値 / bool / null は簡易 coerce。それ以外は文字列扱い。
    """
    if "=" not in expr:
        raise ValueError(f"override must be KEY=VAL: {expr}")
    key, raw = expr.split("=", 1)
    keys = key.split(".")
    value = _coerce(raw)

    # 先頭がステップ名なら pipeline 内の該当エントリへ飛ぶ
    first = keys[0]
    if first in _STEP_NAMES:
        pipeline = data.get("pipeline") or []
        step_entry = next((s for s in pipeline if s.get("step") == first), None)
        if step_entry is None:
            raise KeyError(f"No pipeline step named {first!r}")
        node: Any = step_entry
        path = keys[1:]
    elif first.startswith("pipeline[") and first.endswith("]"):
        idx = int(first[len("pipeline["):-1])
        node = data["pipeline"][idx]
        path = keys[1:]
    else:
        node = data
        path = keys

    for k in path[:-1]:
        if k not in node or not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]

    tail = path[-1]
    node[tail] = value
    logger.info("cassette override: %s = %r", key, value)


def _coerce(s: str) -> Any:
    low = s.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s
