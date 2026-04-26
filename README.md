# meeting-hub

統合型の文字起こし・議事録パイプライン。
既存 2 リポ（`transcription-pipeline` / `seminar-transcription`）を統合し、
5 カセット + ライブ版（商談 / 社内MTG / セミナー / 1on1 / 1on1(ライブ) / 採用面談）で単一コードパスから運用する。

## 実装済機能（Phase 1+2+3+4+5）

- **ファイル投入型**（mp4 / m4a / wav / mp3 → 議事録）
- **ライブ音声キャプチャ**（macOS BlackHole / Windows VB-Cable の 2ch 同時録音）
- **7 Step パイプライン**: `preprocess` / `transcribe` / `diarize` / `term_correct` / `llm_cleanup` / `minutes_extract` / `format`
- **Provider 切替**: カセット YAML で宣言
  - transcribe: `faster_whisper_batch` / `faster_whisper_chunked` / `whisper_streaming`（1〜3秒遅延）/ `whisper_cpp_coreml`（macOS）
  - diarize: `pyannote` / `channel_based` / NeMo 評価骨子
- **5 カセット**（会議タイプ別）+ `--live` フラグで録画／ライブを同カセットで切替 + `--override` でパラメータ一時上書き
- **外部 destinations 実装**: Notion / Slack / Email (Gmail SMTP) / Google Drive アップロード
- **`--resume <run_id>`**: 失敗した場合に checkpoint から途中再開
- **`--dry-run`**: カセット構成を確認
- **`--batch`**: ディレクトリ一括処理
- **Streamlit Web UI** (Phase 3): file upload / cassette 選択 / 進捗表示 / DL / ジョブ履歴 / Live ページ
- **Modal Labs ランタイム** (Phase 3): `runtime: modal` で重い Step を GPU 上で実行
- **Claude Batch API** (Phase 3): `mode=cloud_batch` + `batch_mode: true` で 50%割引
- **認証**: NoAuth / BasicAuth / Google SSO (skeleton)、管理者/一般の 2 層
- **ジョブ履歴**: SQLite で永続化、Step events + 再 DL
- **擬似ストリーム transcribe** (Phase 4): `faster_whisper_chunked` で 20秒 chunk（2秒重複）
- **ライブプロファイル**: `--live` フラグまたは `live://` URI で canonical カセット（sales_meeting 等）を自動ライブ化（旧 `live_*` カセット名は deprecation 互換）
- **NeMo 評価フレームワーク**: DER 計算 + `emit_decision_report()` で判断 Markdown を自動生成
- **真リアルタイム transcribe** (Phase 5): `whisper_streaming`（LocalAgreement-2、1〜3秒遅延）
- **whisper.cpp + Core ML** (Phase 5, macOS): pywhispercpp / CLI / fallback の 3 段検出
- **ライブ字幕** (Phase 5): `core/streaming/realtime_captions.py`（plain / SRT / VTT / JSON + CaptionBroadcaster）
- **ZoomSDKAdapter** (Phase 5): **保留中**（skeleton、復活条件は `docs/SETUP_ZOOM_SDK.md`）

現状は ROADMAP Phase 5 まで全実装済（ZoomSDK を除く）。以降は運用・改善フェーズ。

> 📘 **初めて使う方は [docs/USER_GUIDE.md](./docs/USER_GUIDE.md) をご覧ください**（インストール → 初回実行 → 日常運用まで通しで説明）。

## セットアップ

```bash
# 依存インストール
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 環境変数
cp .env.example .env
# .env に HUGGINGFACE_TOKEN / ANTHROPIC_API_KEY / GOOGLE_APPLICATION_CREDENTIALS を設定

# pyannote モデルのライセンス同意（HF hub）
#   https://huggingface.co/pyannote/speaker-diarization-3.1
#   https://huggingface.co/pyannote/segmentation-3.0

# ffmpeg（macOS）
brew install ffmpeg
```

## 使い方

```bash
# 単一ファイル
python -m cli.main recording.mp4 -c sales_meeting

# 話者数指定（エイリアス）
python -m cli.main recording.mp4 -c sales_meeting --speakers 2

# カセット上書き（任意の key)
python -m cli.main recording.mp4 -c seminar --override transcribe.params.beam_size=3

# ディレクトリ一括
python -m cli.main ./recordings/ -c sales_meeting --batch -o ./output/

# dry-run（パイプライン確認のみ）
python -m cli.main recording.mp4 -c sales_meeting --dry-run

# ライブ音声（1on1、60秒録音、live:// URI 自動検知で --live 不要）
#   macOS: BlackHole + Multi-Output Device 事前設定が必要 (docs/SETUP_LIVE_AUDIO_MACOS.md)
#   Windows: VoiceMeeter Banana + VB-Cable 推奨 (docs/SETUP_LIVE_AUDIO_WINDOWS.md)
python -m cli.main "live://duration=60" -c one_on_one

# resume（途中失敗を継続）
python -m cli.main recording.mp4 -c sales_meeting --resume 20260423_153012_recording
```

### Web UI（Phase 3）

```bash
# 認証なしのローカル開発
streamlit run web/streamlit_app.py

# BasicAuth 有効（チーム共有用途）
export AUTH_MODE=basic
export AUTH_USERS="alice:xxxx:admin,bob:yyyy:user"
streamlit run web/streamlit_app.py --server.address 0.0.0.0
```

詳細: `docs/SETUP_STREAMLIT.md`

出力は `./output/<YYYYMMDD_HHMMSS>_<stem>/` 配下と、カセットの destination（`local`）に保存される。

## ディレクトリ構造

```
meeting-hub/
├── cassettes/               # 5 カセット YAML
├── prompts/                 # Claude 用 system prompt
├── templates/               # Jinja2 議事録テンプレ
├── vocab/terms/             # 用語辞書（business.yaml / it.yaml ...）
├── vocab/initial_prompts/   # Whisper initial_prompt 用
├── core/
│   ├── cassette_schema.py   # Pydantic スキーマ（Phase 0）
│   ├── cassette.py          # YAML ロード + override
│   ├── context.py           # 実行状態
│   ├── pipeline.py          # Step 直列実行
│   ├── metrics.py           # 回帰テスト用メトリクス
│   ├── steps/               # 7 Step 実装
│   ├── adapters/            # InputAdapter（file）
│   ├── destinations/        # local 完全実装 + 他 skeleton
│   ├── llm/claude_client.py # Anthropic SDK ラッパ
│   └── hooks/               # pre/post パイプラインフック
├── cli/main.py              # CLI エントリ
├── tests/                   # unit / integration / regression
├── docs/                    # PHASE0_DESIGN / ROADMAP / USER_GUIDE / FLOW など
└── secrets/                 # SA JSON 等（gitignore）
```

## テスト

```bash
pip install -r requirements-dev.txt

# ユニット + 統合（モック前提、CI 想定）
pytest tests/unit tests/integration -v

# 回帰（golden_samples/ + 実モデル/API、ローカル手動のみ）
GOLDEN_SAMPLES_ROOT=/path/to/golden_samples pytest tests/regression -v
```

## 既知の制約（Phase 5 時点）

- `whisper_streaming` は擬似ストリーム（録音済 WAV を 1 秒窓スライド）。真の live bytes チャンク対応は Phase 6
- **Zoom Meeting SDK は保留**（`core/adapters/zoom_sdk.py` は skeleton、社内承認待ち。`docs/SETUP_ZOOM_SDK.md` 参照）
- NeMo は評価スケルトン（利用者環境で `_run_nemo` 実装 + `pip install nemo_toolkit[asr]`）
- Google SSO は skeleton（Phase 3.5 で本実装予定）
- chunked / streaming provider の Modal runtime 未対応
- Streamlit は 1 プロセス前提、大規模運用時は FastAPI + Next.js に移行検討

詳細は `docs/PHASE5_COMPLETION.md §4` を参照。

## 関連ドキュメント

### 利用者向け
- **[docs/USER_GUIDE.md](./docs/USER_GUIDE.md)** — 初回セットアップから日常運用まで（必読）
- [docs/FLOW.md](./docs/FLOW.md) — 処理フロー図（7 Step × モード別分岐 × data flow）
- [docs/DIARIZATION_SHORT_UTTERANCE.md](./docs/DIARIZATION_SHORT_UTTERANCE.md) — 短発話・頻繁な話者切替への対応調査（弱点・改善案・外部ツール比較）
- [docs/SETUP_LIVE_AUDIO_MACOS.md](./docs/SETUP_LIVE_AUDIO_MACOS.md) / [WINDOWS](./docs/SETUP_LIVE_AUDIO_WINDOWS.md) — ライブ音声セットアップ
- [docs/SETUP_STREAMLIT.md](./docs/SETUP_STREAMLIT.md) — Web UI 起動手順
- [docs/SETUP_MODAL.md](./docs/SETUP_MODAL.md) — Modal Labs GPU 実行
- [docs/SETUP_ZOOM_SDK.md](./docs/SETUP_ZOOM_SDK.md) — Zoom SDK（保留中）
- [docs/FREE_HOSTING_OPTIONS.md](./docs/FREE_HOSTING_OPTIONS.md) — 無料 Web ホスティング比較（HF Spaces + Modal 推奨）

### 開発者・運用者向け
- `docs/PHASE0_DESIGN.md` — 設計決定（プライバシー / モード / カセット）
- `docs/PHASE2_COMPLETION.md` — Phase 2 完了判定・移行ガイド
- `docs/PHASE3_COMPLETION.md` — Phase 3 完了判定・運用ガイド
- `docs/PHASE4_COMPLETION.md` — Phase 4 完了判定・Live 運用
- `docs/PHASE5_COMPLETION.md` — Phase 5 完了判定・真リアルタイム運用
- `docs/ROADMAP.md` — Phase 0〜5 ロードマップ
- `docs/NOTION_DB_SCHEMA.md` — Notion DB スキーマ定義
