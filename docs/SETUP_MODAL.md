# Modal Labs セットアップ

Phase 3 で `transcribe` / `diarize` Step を Modal の GPU 上で実行するためのセットアップ。

## 全体像

```
┌──────────────┐         ┌──────────────┐
│ local        │  audio  │ Modal (A10G) │
│ meeting-hub  │────────►│ transcribe   │
│ Pipeline     │◄────────│ diarize      │
│              │ segments│              │
└──────────────┘         └──────────────┘
```

- 軽量な Step（preprocess / term_correct / llm_cleanup / minutes_extract / format）は **ローカル**
- 重い Step（transcribe / diarize）は **Modal 上の GPU**

## 1. Modal アカウント作成 + 依存インストール

```bash
pip install modal
modal token new
# ブラウザが開き認証 → ~/.modal/config.toml に保存
```

## 2. Secrets を登録

```bash
modal secret create meeting-hub-secrets \
  HUGGINGFACE_TOKEN="hf_xxx" \
  ANTHROPIC_API_KEY="sk-ant-xxx"
```

※ ANTHROPIC_API_KEY は Phase 3 の Modal 関数では未使用（llm_cleanup/minutes_extract は local 実行）
　だが、将来の Batch API Modal 実行を見据えて登録しておく。

## 3. Deploy

```bash
modal deploy scripts/modal_deploy.py
# => App name: meeting-hub
# => Functions: transcribe_on_modal, diarize_on_modal
```

## 4. カセットで Modal を指定

```yaml
# cassettes/sales_meeting_modal.yaml などで
pipeline:
  - step: preprocess
    runtime: local        # 変更なし
  - step: transcribe
    runtime: modal        # ⬅ ここだけ modal にする
  - step: diarize
    runtime: modal
  - step: term_correct
    runtime: local
  ...
```

または既存カセットを `--override` で一時切替:

```bash
python -m cli.main video.mp4 -c sales_meeting \
  --override transcribe.runtime=modal \
  --override diarize.runtime=modal
```

## 5. 利用状況の確認

```bash
modal app list
modal app logs meeting-hub
modal app stats meeting-hub
```

料金確認: https://modal.com/home → Billing。Starter $30/月 無料枠を超えないように `modal.Period` のアラートを設定推奨。

## コスト目安（A10G 使用、2026-04 時点の参考値）

| 音声長 | transcribe 時間 | diarize 時間 | 概算コスト |
|---|---|---|---|
| 10 分 | 〜30秒 | 〜20秒 | < $0.05 |
| 60 分 | 〜2-3 分 | 〜1-2 分 | ~$0.20 |
| 90 分 | 〜3-5 分 | 〜2-3 分 | ~$0.30 |

月 20 件（各 60 分）想定で $3〜$5/月、無料枠 $30 に収まる見込み。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `modal.Function.lookup` が失敗 | `modal app list` で `meeting-hub` が deploy 済か確認 |
| HUGGINGFACE_TOKEN が見えない | `modal secret list` で `meeting-hub-secrets` を確認 |
| GPU が取れない | コールドスタート待ち（初回 30-60 秒）、または A10G が満杯なら A100 に変更 |
| ローカルで動くのに Modal で壊れる | `modal run --detach scripts/modal_deploy.py::transcribe_on_modal --help` でエラー確認 |

## 関連

- `REPORT_PHASE3_PLAN.md §4.3`
- `core/runtime.py`（`ModalRuntime` クラス）
- `scripts/modal_deploy.py`
