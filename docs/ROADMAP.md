# ロードマップ — Phase 0〜5

> 統合プラットフォーム `meeting-hub` の段階的構築計画。
> 各 Phase の完了条件と成果物を明示する。詳細な設計決定は `PHASE0_DESIGN.md` を参照。

---

## Phase 0: 設計確定（3〜5日） — 現在地

### 目標
Phase 1 に入る前に、カセットスキーマ・議事録テンプレ・設計ドキュメントを確定させる。

### 成果物
- [x] `core/cassette_schema.py` — Pydantic スキーマ
- [x] `cassettes/*.yaml` — 5カセット分
- [x] `templates/*.md.j2` — 5カセット分の議事録テンプレ
- [x] `prompts/minutes_extract_*.md` — 5カセット分の Claude プロンプト
- [x] `prompts/cleanup_seminar.md` — セミナー用フィラー除去プロンプト
- [x] `docs/PHASE0_DESIGN.md` — 設計決定サマリ
- [x] `docs/ROADMAP.md` — 本ドキュメント
- [x] `docs/NOTION_DB_SCHEMA.md` — Notion DB構造定義
- [ ] Claude Code 調査プロンプト実行、詳細設計レポート取得（Task 1〜11）
- [ ] 既存2リポで golden sample 取得（商談×2、社内MTG×2、セミナー×2）

### 完了条件
- カセットスキーマが Pydantic で検証可能（`CassetteConfig.model_validate()` が通る）
- 全5カセットの YAML がスキーマ違反なくロード可能
- 既存2リポの `pre-integration-v1.0` タグ打ち

---

## Phase 1: ファイル投入型の統合リポ（1.5〜2週）

### 目標
既存2リポの機能を新リポに完全に統合し、ファイル投入 → 議事録出力までを Step ベースで実行できるようにする。

### 実装対象
- `core/steps/base.py` — Step ABC
- `core/steps/preprocess.py` — 既存 `audio_preprocess.py` + `audio_extractor.py` を統合
- `core/steps/transcribe.py` — provider: `faster_whisper_batch`（既存2リポから集約）
- `core/steps/diarize.py` — provider: `pyannote`（既存 transcription-pipeline から）
- `core/steps/term_correct.py` — TERM_DICT 適用
- `core/steps/llm_cleanup.py` — provider: `claude`（既存 seminar-transcription から）
- `core/steps/minutes_extract.py` — **新規**、Claude で5カセット分の議事録抽出
- `core/steps/format.py` — md/txt/json/srt 出力
- `core/adapters/file.py` — ファイル入力アダプタ
- `core/pipeline.py` — Step 直列実行
- `core/cassette.py` — YAML ロード + バリデーション
- `core/context.py` — パイプライン共有状態
- `cli/main.py` — CLI エントリーポイント

### 完了条件
- 既存2リポで取得した golden sample と同等以上の出力が新リポで得られる
- `sales_meeting` / `seminar` カセットが動作
- pytest で回帰テスト合格

---

## Phase 2: マイク + システム音声 + 議事録抽出（2週）

### 目標
ライブ音声入力（マイク + システム音声 2chキャプチャ）を実装し、全5カセットを動作させる。
ここまでで既存2リポを卒業できる状態にする。

### 実装対象
- `core/adapters/live_audio.py` — 2ch キャプチャ（sounddevice + OS別ドライバ連携）
  - macOS: BlackHole + Multi-Output Device
  - Windows: VB-Cable
  - Linux: PulseAudio module-loopback
- `core/adapters/base.py` — InputAdapter ABC（既存の file と共通IF化）
- `core/pipeline.py` を「一括」「ストリーム」両対応に拡張
- `core/steps/diarize.py` の拡張 — 2ch入力では話者分離を省略可能に
- `cassettes/one_on_one.yaml` を `live_audio` 対応
- Google Drive / Notion / Slack / Gmail 連携（MCP経由）

### 完了条件
- 5カセット全てが動作
- マイク+システム音声キャプチャが macOS / Windows で動作（実利用OS）
- 外部連携（Drive/Notion/Slack/Email）が動作
- チームメンバー全員が1回以上実運用
- 既存2リポからの切替ゴーサイン（詳細は Phase 2 完了時に決定）

### 切替判断チェックリスト（草案）
- [ ] Golden sample 回帰テスト全合格
- [ ] 5カセット動作確認済み
- [ ] 2ch キャプチャが実利用OSで動作
- [ ] 外部連携が動作
- [ ] チームメンバー全員が新リポで1回以上実運用
- [ ] Phase 2 完了レポートの承認

---

## Phase 3: Streamlit Web UI + Modal対応（2〜3週）

### 目標
Web UI を立てて非エンジニアも操作可能にする。重いバッチ処理を Modal に逃がす選択肢を追加。

### 実装対象
- `web/streamlit_app.py` — Streamlit 単一ファイル
- `web/auth.py` — AuthProvider 抽象（NoAuth / BasicAuth / GoogleSSO）
- `web/history.py` — SQLite でジョブ履歴管理
- `core/runtime/modal_adapter.py` — `@step_runtime("modal")` デコレータ
- `core/runtime/local_adapter.py` — ローカル実行
- Modal Secrets に HF_TOKEN / ANTHROPIC_API_KEY を登録

### 完了条件
- Streamlit で file upload → cassette 選択 → 進捗 → DL ができる
- ジョブ履歴が保存・閲覧できる
- `runtime: modal` を指定した Step が Modal 上で動作
- Modal 無料枠 $30/月 以内で運用可能なことを実測で確認

---

## Phase 4: 擬似リアルタイム化（2〜3週）

### 目標
ライブ入力からの擬似ストリーミング文字起こしを実現（5〜10秒遅延、完全ローカル）。

### 実装対象
- `core/steps/transcribe.py` に provider `faster_whisper_chunked` を追加
- `core/streaming/buffer.py` — チャンク化バッファ（10〜30秒単位）
- `core/streaming/pipeline.py` — 非同期パイプライン
- ライブカセット（`live_sales` / `live_internal` 等）の追加
- NeMo 話者分離の評価（pyannote比較、日本語ベンチマーク）
- `cassettes/live_*.yaml` の追加

### 完了条件
- ライブ入力で会議終了後30秒以内に初版議事録が完成
- 擬似ストリーミング中の部分文字起こしが Web UI に表示される
- NeMo の評価結果に基づき pyannote 継続 or 切替を決定

---

## Phase 5: 真リアルタイム化 + Zoom SDK（1〜2ヶ月）

### 目標
1〜3秒遅延の真リアルタイム文字起こし。Zoom特化カセットの追加（optional）。

### 実装対象
- `core/steps/transcribe.py` に provider を追加
  - `whisper_streaming`（LocalAgreement-2方式、1〜3秒遅延）
  - `whisper_cpp_coreml`（Mac専用、2〜5秒遅延、高精度）
- `core/adapters/zoom_sdk.py` — Zoom Meeting SDK Raw Data アダプタ（optional）
- `core/streaming/realtime_captions.py` — ライブ字幕
- 社内管理者に Zoom Marketplace 開発者登録の可否を確認（Phase 5 実装直前）

### 完了条件
- 1〜3秒遅延でライブ字幕表示が可能
- Zoom SDK が実装された場合、Zoom会議で話者毎分離済みのライブ字幕が取れる
- 全てローカル完結で動作することを確認

### Phase 5 直前チェックリスト
- [ ] Zoom 有料プランが Meeting SDK 利用条件を満たすか再確認
- [ ] 社内管理者に Marketplace 開発者登録の可否を確認
- [ ] Python バインディングの OSS 状況を調査
- [ ] 実装工数 vs 得られる精度向上を再評価

---

## 依存関係と並行可能性

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5
                                         │
                                         └──→ (並行可能: Modal対応)
```

- Phase 2 → Phase 3 は**一部並行可能**（Web UI と Modal対応は独立）
- Phase 4 の NeMo 評価と Phase 3 の Modal対応は**並行可能**
- Phase 5 の Zoom SDK は **optional**、実装しなくても Phase 5 は完了可能
