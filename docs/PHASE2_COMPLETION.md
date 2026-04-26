# Phase 2 完了レポート

> **目的**: `meeting-hub` Phase 2（ライブ音声 + 外部連携 + 既存2リポ卒業）の完了判定資料。
> 既存2リポ（`transcription-pipeline` / `seminar-transcription`）からの切替ゴーサインの根拠となる。

---

## 1. 完了チェックリスト（ROADMAP §Phase 2 草案 + 追加）

- [ ] Golden sample 回帰テスト全合格（`tests/regression/`、実音声 + metrics.json）
- [ ] 5 カセット動作確認（sales_meeting / internal_meeting / seminar / one_on_one / one_on_one_live / interview）
- [ ] 2ch キャプチャが macOS / Windows で動作（実利用 OS）
- [ ] 外部連携（Drive / Notion / Slack / Email）が動作
- [ ] チームメンバー全員が 1 回以上実運用
- [ ] 既存2リポ README に統合リポ誘導が追記済
- [ ] 既存2リポに `pre-integration-v1.0` タグ打ち済（§12-12、Phase 1 開始前）
- [ ] `meeting-hub` に Phase 2 完了タグ（例: `v0.2.0`）打ち済
- [ ] Phase 2 完了レポートの承認

---

## 2. 実装サマリ

### 2.1 M7: ライブ音声キャプチャ
- `core/adapters/live_audio.py`（macOS BlackHole / Windows VB-Cable 両対応）
- `parse_live_uri()` で `live://duration=60` 形式をパース
- `_auto_detect_device()` で OS 別の既知の仮想オーディオデバイスを自動検出
- `docs/SETUP_LIVE_AUDIO_{MACOS,WINDOWS}.md` にセットアップ手順を記録

### 2.2 M8: Pipeline ストリーム対応 + `--resume`
- `Pipeline.run(resume_run_id=...)` で checkpoint から再開
- `{work_dir}/checkpoints/{step_name}.json` + `*_segments.json` / `*_cleaned.txt` / `*_minutes.json` を保存
- CLI: `--resume <run_id>` / `--record-seconds <SEC>`

### 2.3 M9: 外部 destinations 本実装（直接 SDK）
（Phase 6 リファクタで `core/destinations.py` 単一モジュールに統合済）
- `NotionDestinationImpl` — notion-client + `${NOTION_DB_*}` env 展開 + `_build_properties`
- `SlackDestinationImpl` — slack-sdk + `summary_only` / `full_minutes`
- `EmailDestinationImpl` — smtplib + Gmail app password（§8-3 RESOLVED）
- `GoogleDriveDestinationImpl` — サービスアカウントで upload、`drive-folder://<id>` 形式

### 2.4 M10: channel_based diarize + one_on_one_live カセット
- `diarize` Step に `provider=channel_based` 追加（RMS 比で Ch0/Ch1 を割当）
- `cassettes/one_on_one_live.yaml` 新規（mode=local_llm, input.type=live_audio, mix=separate）
- `one_on_one.yaml`（file）と `one_on_one_live.yaml`（live）を分離（§8-5 RESOLVED）

---

## 3. テスト実績

**ユニット + 統合**: 全 88 テスト以上 PASS（M10 時点）
```
tests/unit/core/        — 11件（context, step_registry, pipeline, resume）
tests/unit/steps/        — 28件（7 Step × 複数ケース + channel_based）
tests/unit/adapters/     — 13件（file + live_audio）
tests/unit/destinations/ — 16件（notion, slack, email, google_drive）
tests/integration/       — 8件（6カセットロード + override）
```

**回帰テスト**: Phase 2 では skeleton 継続（§12-9 RESOLVED、モック前提）

---

## 4. 既存2リポ → meeting-hub 移行ガイド

### 4.1 コマンド対応表

| 既存コマンド | meeting-hub 相当 |
|---|---|
| `cd transcription-pipeline && python run.py meeting.mp4 --speakers 2` | `python -m cli.main meeting.mp4 -c sales_meeting --speakers 2` |
| `cd transcription-pipeline && python run.py ./recordings/ --batch` | `python -m cli.main ./recordings/ -c sales_meeting --batch` |
| `cd seminar-transcription && python main.py seminar.mp4 --format md` | `python -m cli.main seminar.mp4 -c seminar` |
| `cd seminar-transcription && python main.py seminar.mp4 --skip-claude` | `python -m cli.main seminar.mp4 -c seminar --skip-claude` |
| `cd seminar-transcription && python main.py seminar.mp4 --split-speakers` | 未移植（Phase 3 で `diarize.provider=claude` 検討） |

### 4.2 設定ファイル対応

| 既存（env / config.py） | meeting-hub |
|---|---|
| `HUGGINGFACE_TOKEN` | 同名 env、`.env` に記載 |
| `ANTHROPIC_API_KEY` | 同名 env |
| `WHISPER_MODEL`（env） | カセット `transcribe.params.model`（`--override` で一時変更可） |
| `NUM_SPEAKERS`（config.py） | カセット `diarize.params.num_speakers` |
| `TERM_DICT`（config.py） | `vocab/terms/*.yaml` + カセット `terms.stack` |
| `--denoise`（seminar CLI） | `--denoise`（CLI エイリアス維持） |

### 4.3 カセット選定の目安

| 既存ユースケース | 推奨カセット |
|---|---|
| 商談録画 | `sales_meeting` |
| 社内MTG 録画 | `internal_meeting` |
| セミナー録画 | `seminar` |
| 1on1 録画 | `one_on_one` |
| **1on1 ライブ（マイク+システム音声）** | `one_on_one_live` |
| 採用面談 | `interview` |

---

## 5. 既知の制約（Phase 3 以降に持ち越し）

1. **Batch API は messages API 直通**（§12-2）— Phase 3 の Modal 連動で本実装予定
2. **真リアルタイムなし** — Phase 2 は録音完了後バッチ処理。Phase 4 で擬似ストリーム、Phase 5 で真リアルタイム
3. **Zoom SDK 非対応** — Phase 5 optional（Marketplace 登録次第）
4. **Web UI なし** — Phase 3 で Streamlit
5. **回帰テストの実モデル未接続** — `tests/regression/` は骨子のみ。ローカル手動で golden_samples 取得後に有効化
6. **channel_based diarize の精度** — クロストーク（両者同時発話）には弱い。RMS 比 0.6 未満の場合は大きい方を採用するフォールバック

---

## 6. Phase 3 への申し送り

- Streamlit Web UI（file upload / cassette 選択 / 進捗 / DL / job 履歴）
- Modal Labs ランタイム（`runtime: modal` の Step 実装、Batch API も Modal 連動で）
- AuthProvider 抽象（Phase 3 実装直前に認証方式確定）
- SQLite ジョブ履歴
- `minutes_extract.provider=claude` の Prompt Caching 強化（cache_control の扱いを再検証）

---

## 7. 切替ゴーサイン（承認欄）

```
□ Phase 2 完了レポート承認
□ チーム全員が新リポで 1 回以上実運用
□ 既存2リポの README に統合リポ誘導追記完了
□ `meeting-hub` に v0.2.0 タグ打ち
□ 既存2リポへの新機能追加を以降停止（バグ修正のみ継続）

承認日: 2026-MM-DD
承認者:
```
