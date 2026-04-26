# Phase 0 設計決定サマリ

> 本ドキュメントは、ユーザーとの対話で確定した Phase 0 の設計決定を集約した
> 正式な記録です。以降の Phase 1〜5 の実装判断は、このドキュメントを基準に行います。

---

## 1. アーキテクチャ方針

| 項目 | 決定 |
|---|---|
| 統合方式 | **B案**（完全統合、単一新リポ）+ **C案部分採用**（Stepインターフェース化） |
| フレームワーク化 | 過度にフレームワーク化しない（純粋なPython継承で済ませる） |
| 入力抽象 | InputAdapter で file / live_audio / zoom_sdk を吸収 |
| Step抽象 | `Step.process(ctx: Context) -> Context` の単純IF |
| provider切替 | 同Stepで複数実装を持ち、カセットで選択（例: diarize.provider: pyannote\|nemo） |

## 2. プライバシー制約（最重要）

リアルタイムはローカル完結、外部音声API原則禁止。
カセットに `mode` フィールド（4段階）を必須化。

| mode | 外部音声API | Claude API(テキスト) | Modal GPU(バッチ) | Modal GPU(ライブ) |
|---|---|---|---|---|
| local | ✕ | ✕ | ✕ | ✕ |
| local_llm | ✕ | ◯ | ✕ | ✕ |
| cloud_batch | ✕ | ◯ | ◯ | ✕ |
| cloud | ◯ | ◯ | ◯ | ◯ |

**ルール**:
- ライブ音声は Modal に送らない（プライバシー要件）
- 1on1 / 採用面談は `local_llm` を既定
- Deepgram / AssemblyAI / OpenAI Realtime は **採用しない**
- Zoom RTMS も **不採用**（Zoomサーバ経由のためローカル完結と両立しない）

## 3. 入力優先順位

| 順位 | 方式 | フェーズ |
|---|---|---|
| 1 | マイク + システム音声 2chキャプチャ（OS汎用） | Phase 2 |
| 2 | 録画mp4 / m4a（バッチ） | Phase 1 |
| 3 | Zoom Meeting SDK Raw Data（Zoom限定、optional） | Phase 5 |

「ZoomとMeet両方利用」のため、Phase 2 の OS汎用キャプチャを本命解とする。
Zoom SDK は Phase 5 実装直前に再考。

## 4. 技術スタック

| 項目 | 採用 | 備考 |
|---|---|---|
| 文字起こし | faster-whisper large-v3 / large-v3-turbo | int8 / CPU 既定、将来 MPS/CoreML 検証 |
| 話者分離 | pyannote 3.1 | Phase 4 で NeMo を評価、結果次第で切替 |
| LLM | Claude Haiku 4.5 | $1/$5 per MTok、Batch APIで50%割引 |
| 音声前処理 | noisereduce + librosa + ffmpeg | 既存資産を踏襲 |
| リアルタイム候補 | faster_whisper_chunked / whisper_streaming / whisper_cpp_coreml | すべてローカル |
| GPU | Modal Labs（Starter無料枠 $30/月） | バッチ専用、ライブ禁止 |

## 5. Web UI（Phase 3）

| 項目 | 決定 |
|---|---|
| 技術 | **Streamlit** 最小構成開始、必要に応じ FastAPI+Next.js へ拡張 |
| 機能 | アップロード / カセット選択 / 進捗表示 / 結果ダウンロード / ジョブ履歴 |
| 起動 | localhost（各自PC）+ チーム共有サーバの両対応 |
| 認証 | Phase 3 実装直前に再決定（AuthProvider 抽象化で吸収） |
| 権限 | 管理者 / 一般の2層 |

### 権限マトリクス

| 操作 | 管理者 | 一般 |
|---|---|---|
| 文字起こし実行 | ◯ | ◯ |
| 自分のジョブ履歴閲覧 | ◯ | ◯ |
| 他人のジョブ履歴閲覧 | ◯ | ✕ |
| カセット追加・編集 | ◯ | ✕ |
| TERM_DICT編集 | ◯ | ✕ |
| 宛先リスト編集 | ◯ | ✕ |
| Notion DB接続設定 | ◯ | ✕ |
| ジョブ削除 | 全員分 | 自分のみ |
| ユーザー追加 | ◯ | ✕ |

## 6. 保管・連携

| データ | 保管先 |
|---|---|
| 音声・中間ファイル | Google Drive |
| 議事録（最終） | Local + Notion DB + Slack + メール |
| ジョブ履歴（メタ） | Local SQLite |
| 保管期間 | 制限なし、手動削除 |

### Notion 連携
- データベースに行追加形式
- カセットごとに異なる DB を用意（`NOTION_DB_SALES` / `NOTION_DB_INTERNAL` / `NOTION_DB_SEMINAR` / `NOTION_DB_RECRUITING`）
- 1on1 は Notion 連携なし

### Slack 連携
- カセットごとにチャンネル指定（`#sales-minutes` / `#internal-minutes` 等）
- 1on1 / 面談は Slack 連携なし

### メール連携
- カセットごとに固定の送信先リストを YAML で保持
- 1on1 / 面談 / セミナー は メール連携なし（sales_meeting のみ）

## 7. 5カセット定義

| カセット | mode | 話者分離 | Claude整形 | 議事録抽出 | 配信先 |
|---|---|---|---|---|---|
| sales_meeting | cloud_batch | ◯ (2名) | ◯ | ◯ | local + drive + notion + slack + email |
| internal_meeting | cloud_batch | ◯ (自動) | ◯ | ◯ | local + drive + notion + slack |
| seminar | cloud_batch | △ (既定OFF) | ◯ | ◯ | local + drive + notion |
| one_on_one | **local_llm** | ◯ (2名) | ◯ | ◯ | **local のみ** |
| interview | **local_llm** | ◯ (2-4名) | ◯ | ◯ | local + notion（採用DB） |

## 8. 切替計画

| 項目 | 決定 |
|---|---|
| 新リポ切替タイミング | Phase 2 完了時 |
| 既存リポの扱い | 残置（削除・アーカイブしない）、新機能追加は停止 |
| 切替判断ゴーサイン | 保留（Phase 2完了時に再検討） |
| 並存期間中のSource of Truth | 既存リポ（Phase 2 完了まで） |

### 並存時のルール
- 既存2リポの README 冒頭に統合リポへの誘導を追記
- 既存リポはバグ修正のみ、新機能は追加しない
- Phase 0 完了時点で既存リポに `pre-integration-v1.0` タグを打つ

## 9. 予算とコスト

| 項目 | 想定 |
|---|---|
| Claude Haiku 4.5 | 月 $1〜2（チーム利用規模で） |
| Modal Labs | Starter 無料枠内 $0 |
| faster-whisper / pyannote | 無料 |
| Google Drive / Notion / Slack | 既存契約を利用 |
| **月額合計見込み** | **$1〜5** |

## 10. 段階的ロードマップ

| Phase | 期間 | 主要成果物 |
|---|---|---|
| **0** | 3〜5日 | カセットスキーマ・5カセットYAML・議事録テンプレ・設計ドキュメント |
| **1** | 1.5〜2週 | ファイル投入型の統合リポ、既存同等の出力を再現、sales_meeting/seminar動作 |
| **2** | 2週 | マイク+システム音声2chキャプチャ、議事録抽出Step、5カセット全動作 |
| **3** | 2〜3週 | Streamlit Web UI、Modal対応（バッチ）、ジョブ履歴 |
| **4** | 2〜3週 | 擬似リアルタイム化（faster-whisperチャンキング、完全ローカル） |
| **5** | 1〜2ヶ月 | 真リアルタイム化、NeMo評価、Zoom SDK（optional） |

---

## 補足: 未解決事項

以下は実装直前に再決定する:

1. Phase 3 の Web UI 認証方式（Google SSO / Basic / VPN-only）
2. Phase 2 切替のゴーサインチェックリスト具体化
3. Phase 5 の Zoom SDK 採否（Marketplace 開発者登録の社内可否含む）
4. Notion DB の実構築（5カセット分のDB作成）
5. TERM_DICT の分割ルール（会社固有と共通の線引き）
