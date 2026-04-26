# Phase 5 完了レポート

> **目的**: `meeting-hub` Phase 5（真リアルタイム transcribe + ZoomSDK 保留 + NeMo 判断）の完了判定資料。

---

## 1. 完了チェックリスト

- [ ] `transcribe.provider=whisper_streaming` で 1〜3 秒遅延ライブ字幕（実機検証）
- [ ] `transcribe.provider=whisper_cpp_coreml` が macOS で動作（pywhispercpp or CLI、実機検証）
- [ ] `CaptionBroadcaster` が Streamlit Live ページ等で活用できる状態
- [ ] ZoomSDK は skeleton で誤用が防げる（NotImplementedError + docs/SETUP_ZOOM_SDK.md）
- [ ] `emit_decision_report()` で NeMo 採用判定の Markdown が出る
- [ ] 全てローカル完結（外部音声 API に依存しない）
- [ ] `docs/PHASE5_COMPLETION.md` 承認

---

## 2. 実装サマリ

### 2.1 新規ファイル
- `core/streaming/local_agreement.py` — LocalAgreement-2 アルゴリズム
- `core/streaming/realtime_captions.py` — ライブ字幕 + ブロードキャスタ
- `core/adapters/zoom_sdk.py` — skeleton
- `tests/unit/streaming/test_local_agreement.py`（11）
- `tests/unit/streaming/test_realtime_captions.py`（14）
- `tests/unit/steps/test_whisper_cpp_coreml.py`（3）
- `tests/unit/adapters/test_zoom_sdk.py`（4）
- `docs/SETUP_ZOOM_SDK.md` — 保留条件ドキュメント
- `REPORT_PHASE5_PLAN.md`
- `docs/PHASE5_COMPLETION.md`（本書）

### 2.2 更新ファイル
- `core/steps/transcribe.py` — `WhisperStreamingStep` + `WhisperCppCoremlStep` 追加
- `core/streaming/__init__.py` — 新 API を re-export
- `core/adapters/__init__.py` — ZoomSDKAdapter を re-export
- `core/evaluation.py` — `emit_decision_report()` 追加
- `tests/unit/core/test_evaluation.py` — +4 件

---

## 3. 運用ガイド

### 3.1 whisper_streaming の有効化

カセット YAML で provider を切替:
```yaml
pipeline:
  - step: transcribe
    provider: whisper_streaming
    params:
      model: large-v3-turbo
      update_interval_sec: 1.0
      merge_gap_sec: 0.8
```

または既存カセットで `--override`:
```bash
python -m cli.main "live://duration=120" -c live_sales \
  --override transcribe.provider=whisper_streaming
```

### 3.2 whisper_cpp_coreml の有効化（macOS）

```bash
# 方法A: pywhispercpp を入れる
pip install pywhispercpp

# 方法B: whisper.cpp をビルドして main バイナリを置く
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && make -j
export MEETING_HUB_WHISPER_CPP_BIN=$(pwd)/main

# モデル DL（ggml 形式）
bash ./models/download-ggml-model.sh large-v3-turbo
# 既定の探索先: ~/.whisper.cpp/models/
```

カセット設定:
```yaml
- step: transcribe
  provider: whisper_cpp_coreml
  params:
    model: large-v3-turbo
    threads: 4
```

### 3.3 ライブ字幕の書き出し

```python
from core.streaming.realtime_captions import CaptionBroadcaster, write_live_caption_file

broadcaster = CaptionBroadcaster()
handler = write_live_caption_file(broadcaster, "live.srt", fmt="srt")
broadcaster.subscribe(handler)

# StreamingPipeline の on_partial に渡す
pipe = StreamingPipeline(cassette, adapter, on_partial=broadcaster.feed)
```

### 3.4 NeMo 採用判定（利用者実機）

```python
from pathlib import Path
from core.evaluation import emit_decision_report, run_benchmark

results = run_benchmark(
    Path("sample.wav"),
    Path("sample.rttm"),
    providers=["pyannote", "nemo"],
    params={"num_speakers": 2},
)
md = emit_decision_report(results, output_path=Path("diarize_decision.md"))
print(md)
```

### 3.5 ZoomSDK の現状

保留中。会議音声は **LiveAudioAdapter**（BlackHole/VB-Cable）で取得可能。復活条件は `docs/SETUP_ZOOM_SDK.md` を参照。

---

## 4. 既知の制約

1. **whisper_streaming は擬似ストリーム** — 録音済 WAV を 1 秒窓でスライドし LocalAgreement-2 を適用。真の live audio bytes チャンクからの入力は Phase 6 で対応予定。
2. **whisper_cpp_coreml の pywhispercpp は実装サンプルレベル** — 実運用前に timestamp の単位（centi-sec）を公式 API と再確認推奨。
3. **ZoomSDK 本実装なし** — 代替策で運用可能。
4. **NeMo 評価はスケルトン依存** — `_run_nemo` の実装は利用者側。閾値 `der_threshold` / `speed_threshold_ratio` は環境に応じて調整。

---

## 5. Phase 6 以降の申し送り（ROADMAP 外）

- `whisper_streaming` の live bytes チャンク対応（真リアルタイム）
- ZoomSDK 本実装（社内承認後）
- Streamlit Live ページの LocalAgreement 可視化（committed / hypothesis 色分け）
- NeMo 本採用時の Step 実装（`@Step.register("diarize", "nemo")`）

---

## 6. 承認欄

```
□ Phase 5 完了レポート承認
□ whisper_streaming で 1〜3 秒遅延の実測確認
□ whisper_cpp_coreml が macOS で動作（pywhispercpp or CLI いずれか）
□ ZoomSDK 保留状態の合意
□ meeting-hub に v0.5.0 タグ打ち

承認日: 2026-MM-DD
承認者:
```
