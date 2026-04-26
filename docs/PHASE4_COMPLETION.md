# Phase 4 完了レポート

> **目的**: `meeting-hub` Phase 4（擬似ストリーム transcribe + ライブカセット + NeMo 評価骨子 + Live UI）の完了判定資料。

---

## 1. 完了チェックリスト

- [ ] `faster_whisper_chunked` provider で長尺音声が chunk 単位に処理される（単体・統合テスト緑）
- [ ] StreamingJob の partial_events で部分結果を受け取れる
- [ ] `live_sales.yaml` / `live_internal.yaml` / `one_on_one_live.yaml` が validation を通る
- [ ] Streamlit の Live ページで part result が 1 秒刻みで更新される
- [ ] `core/evaluation.py` が pyannote で動作（ユーザー実機で）
- [ ] 実音声（60〜90 分）で「録音終了 → 30 秒以内に議事録 md 出力」を確認（ユーザー実機）
- [ ] NeMo のベンチ結果に基づき pyannote 継続 or 切替を決定（ユーザー判断）

---

## 2. 実装サマリ

### 2.1 新規ファイル
- `core/streaming/__init__.py` / `buffer.py` / `pipeline.py`
- `core/evaluation.py`（Phase 6 リファクタで統合、旧 `core/evaluation/{__init__,diarize_benchmark}.py`）
- `cassettes/live_sales.yaml`
- `cassettes/live_internal.yaml`
- `tests/unit/streaming/test_buffer.py`
- `tests/unit/streaming/test_streaming_pipeline.py`
- `tests/unit/core/test_evaluation.py`
- `REPORT_PHASE4_PLAN.md`
- `docs/PHASE4_COMPLETION.md`（本書）

### 2.2 更新ファイル
- `core/steps/transcribe.py` — `_WhisperCore` 共通化 + `FasterWhisperChunkedStep`
- `web/streamlit_app.py` — Live ページ追加、ナビに "Live" 挿入
- `tests/integration/test_cassette_loading.py` — live_sales / live_internal を検証
- `README.md` — Phase 4 機能追記

### 2.3 パラメータ既定値
| キー | 既定 | 備考 |
|---|---|---|
| `transcribe.params.chunk_sec` | 20.0 | Whisper attention + 文境界 |
| `transcribe.params.overlap_sec` | 2.0 | 境界吸収 |
| `merge_overlapping_segments.dedup_threshold_sec` | 0.5 | 近接重複の削除閾値 |

---

## 3. 運用ガイド

### 3.1 CLI での擬似ストリーム

```bash
# live_sales カセット（Streamlit 以外でも使える）
python -m cli.main "live://duration=120" -c live_sales

# batch transcribe と同じ CLI インターフェースだが、
# 内部で chunked provider が動くので進捗ログがチャンクごとに出る
```

### 3.2 Streamlit Live ページ

```bash
streamlit run web/streamlit_app.py
# サイドバー → Live を選択
# ライブカセットを選び、録音時間とチャンク設定をスライダで指定して開始
```

### 3.3 NeMo vs pyannote ベンチ（ユーザー実機）

```bash
pip install nemo_toolkit[asr]   # 重い。GPU 推奨
# core/evaluation.py の _run_nemo() を実装
python -c "
from core.evaluation import run_benchmark
from pathlib import Path
results = run_benchmark(
    Path('sample.wav'),
    Path('sample.rttm'),  # RTTM 形式の ground truth
    providers=['pyannote', 'nemo'],
    params={'num_speakers': 2},
)
for r in results:
    print(f'{r.provider}: DER={r.der:.3f} speakers={r.num_speakers_detected} elapsed={r.elapsed_sec:.1f}s')
"
```

---

## 4. 既知の制約

1. **真リアルタイム未実装** — Phase 5 で whisper_streaming + LocalAgreement-2
2. **NeMo 実呼び出しはスケルトン** — `_run_nemo` を利用者環境で実装（依存の都合）
3. **Streamlit Live の poll は 1 秒固定** — 細かい UX 改善は Phase 5
4. **chunked provider はローカル実行のみ** — Modal runtime には未対応（Phase 5 で検討）
5. **live_internal は mono_merge でチャネル情報ロス** — pyannote の都合、`mix: separate` + channel_based に切替可能

---

## 5. Phase 5 への申し送り

- `transcribe.provider=whisper_streaming`（LocalAgreement-2、1〜3 秒遅延）
- `transcribe.provider=whisper_cpp_coreml`（macOS、2〜5 秒、高精度）
- `core/adapters/zoom_sdk.py`（Zoom Meeting SDK Raw Data、optional）
- `core/streaming/realtime_captions.py`（ライブ字幕）
- NeMo 本採用可否の判断（実機ベンチ結果に基づく）

---

## 6. 承認欄

```
□ Phase 4 完了レポート承認
□ ライブ入力で会議終了後 30 秒以内に初版議事録が完成（実測）
□ Streamlit Live ページで擬似ストリームが動作
□ NeMo のベンチ結果に基づく方針決定
□ `meeting-hub` に v0.4.0 タグ打ち

承認日: 2026-MM-DD
承認者:
```
