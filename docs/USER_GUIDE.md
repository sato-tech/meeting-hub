# meeting-hub 利用者ガイド

録画した会議・セミナー・1on1 などから、**文字起こし → 話者分離 → 用語補正 → 議事録抽出 → 配信**までを自動化するツールです。このガイドは実際に使う方向けに、**インストールから日常運用まで**を順を追って説明します。

---

## 目次

1. [このツールでできること](#1-このツールでできること)
2. [準備するもの](#2-準備するもの)
3. [初回セットアップ](#3-初回セットアップ)
4. [どのカセットを選ぶか](#4-どのカセットを選ぶか)
5. [使い方 3 パターン](#5-使い方-3-パターン)
6. [出力ファイルの見方](#6-出力ファイルの見方)
7. [シナリオ別の実践例](#7-シナリオ別の実践例)
8. [応用機能](#8-応用機能)
9. [議事録を Notion / Slack / メール / Drive に送る設定](#9-議事録を-notion--slack--メール--drive-に送る設定)
10. [プライバシーモードの使い分け](#10-プライバシーモードの使い分け)
11. [コスト感](#11-コスト感)
12. [トラブルシューティング](#12-トラブルシューティング)
13. [FAQ](#13-faq)

---

## 1. このツールでできること

| 入力 | 処理 | 出力 |
|---|---|---|
| 動画 (mp4/mov) / 音声 (m4a/mp3/wav) | 音声抽出 → 文字起こし → 話者分離 → 用語補正 → AI整形 → 議事録抽出 | Markdown 議事録 / JSON / SRT 字幕 / TXT |
| マイク+システム音声 (ライブ) | 上記に加えて 2ch 録音 or 擬似リアルタイム字幕 | 同上 + ライブ字幕 |

### 代表的な用途

- 商談の議事録化（顧客ニーズ・ネクストアクション抽出付き）
- 社内MTG の自動記録（Notion / Slack 配信）
- 60〜90 分のセミナー録画から構造化議事録
- 1on1 の完全ローカル文字起こし（プライバシー重視、外部送信ゼロ）
- 採用面談の記録

---

## 2. 準備するもの

### ハードウェア
- **メモリ**: 8GB 以上（large-v3 Whisper 実行のため）
- **ディスク**: 10GB 以上の空き（モデルキャッシュ + 出力）
- **CPU**: できれば Apple Silicon 系（Intel でも動作可）

### ソフトウェア
- **Python 3.10 以上**（3.11 / 3.12 / 3.13 推奨）
- **ffmpeg**（必須、音声抽出で使用）
- macOS の場合: Homebrew
- ライブ音声キャプチャを使うなら:
  - macOS: **BlackHole 2ch** + Multi-Output Device（[セットアップ手順](./SETUP_LIVE_AUDIO_MACOS.md)）
  - Windows: **VoiceMeeter Banana + VB-Cable**（[セットアップ手順](./SETUP_LIVE_AUDIO_WINDOWS.md)）

### API キー（用途に応じて）
- **Hugging Face Token**（無料）: 話者分離 (pyannote) を使うとき必須
- **Anthropic Claude API Key**（有料、月 $1〜5 目安）: 議事録整形・抽出に使用
- **Notion / Slack / Gmail / Google Drive**（任意）: 議事録を自動配信する場合

---

## 3. 初回セットアップ

### 3.1 リポジトリと Python 環境

**専用の仮想環境を必ず使ってください。** pyenv や Anaconda の「グローバル」環境に `pip install -r requirements.txt` すると、既に入っている別ツール用パッケージ（例: 古い `torchvision`、Prophet 周辺の `httpstan`）とバージョンが食い違い、pip が末尾に `dependency conflicts` と警告することがあります。本ツールは **Python 3.10 以上**（§2）で切った venv に依存だけを入れるのが確実です。

```bash
# 取得
git clone <meeting-hub リポジトリURL>
cd meeting-hub

# 仮想環境（例: システムに python3.11 がある場合）
python3.11 -m venv venv
# python3.10 / python3.12 でも可。python3 のみの場合は python3 -m venv venv

source venv/bin/activate          # macOS / Linux
# Windows は: venv\Scripts\activate

# 依存ライブラリ（venv 内の pip を使う）
python -m pip install -U pip setuptools wheel   # 任意だが解決が安定しやすい
pip install -r requirements.txt
```

**`pip install` の末尾について**: ログの直前に `Successfully installed ...` と一覧が出ていれば、**インストール自体は完了していることがほとんど**です。その直後に `ERROR: pip's dependency resolver ... dependency conflicts` と出る場合は、上記のとおり **同じ環境に残っている他用途のパッケージ** が原因の警告です。venv を新規作成し直すか、別プロジェクト用のパッケージを別環境に分けると警告は消えやすくなります。

### 3.2 ffmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows
# https://ffmpeg.org/download.html からダウンロードして PATH に追加
```

### 3.3 環境変数 `.env`

```bash
cp .env.example .env
```

`.env` を開き、**利用する機能の分だけ**設定します。全部埋める必要はありません。

| 変数 | 必要性 | 取得先 |
|---|---|---|
| `HUGGINGFACE_TOKEN` | 話者分離を使うなら **必須** | https://huggingface.co/settings/tokens |
| `ANTHROPIC_API_KEY` | 議事録整形・抽出を使うなら **必須** | https://console.anthropic.com/ |
| `NOTION_API_KEY` + `NOTION_DB_*` | Notion 配信するなら | https://www.notion.so/profile/integrations |
| `SLACK_BOT_TOKEN` | Slack 配信するなら | Slack App 作成 + チャンネル追加 |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` | Gmail でメール送信するなら | Google アカウント → 2段階認証 → アプリパスワード |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Drive 使うなら | GCP → サービスアカウント → JSON 鍵 |

### 3.4 pyannote モデルのライセンス同意（話者分離を使う人のみ）

Hugging Face にログインした状態で以下 2 ページの "Accept" をクリック:
- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

### 3.5 動作確認

```bash
# カセット構成を確認（dry-run、処理はしない）
python -m cli.main sample.mp4 -c sales_meeting --dry-run
```

期待出力:
```
─── dry-run: cassette summary ───
name:  sales_meeting
mode:  cloud_batch
  ✓ preprocess (provider=None) ...
  ✓ transcribe (provider=faster_whisper_batch) ...
  ✓ diarize (provider=pyannote) ...
  ...
  → local / notion / slack / email / google_drive
```

dry-run が通れば準備完了です。

---

## 4. どのカセットを選ぶか

カセット = 用途別の設定プロファイル。会議タイプ別の **5 本** で、**同じカセットを録画とライブ両方に使えます**（`--live` フラグで切替）。

| カセット | 用途 | 話者 | AI整形 | 主な配信先 | プライバシー |
|---|---|---|---|---|---|
| `sales_meeting` | 商談・アポ | 2 名 | ◯ | Notion / Slack / メール / Drive | 外部OK |
| `internal_meeting` | 社内MTG | 自動 | ◯ | Notion / Slack / Drive | 外部OK |
| `seminar` | セミナー・講演 | 基本オフ | ◯ | Notion / Drive | 外部OK |
| `one_on_one` | 1on1 | 2 名 | ◯ | **ローカルのみ** | **最優先** |
| `interview` | 採用面談 | 2〜4 名 | ◯ | 採用 DB | 中 |

### 録画 vs ライブの切替

```bash
# 録画ファイル（既定、バッチ処理）
python -m cli.main meeting.mp4 -c sales_meeting

# ライブ録音（--live でプロファイル切替 or live:// URI で自動判定）
python -m cli.main "live://duration=60" -c sales_meeting
```

`--live`（または `live://` URI）を付けると、同じカセットから以下が自動適用されます:
- transcribe: `faster_whisper_batch` → `faster_whisper_chunked`（chunk 20秒、重複 2秒）
- model: `large-v3` → `large-v3-turbo`（速度優先）
- diarize: `pyannote` → `channel_based`（2ch キャプチャを話者ラベルに直変換）
- preprocess: `default` → `simple`（ノイズ除去スキップで高速）
- llm.batch_mode: `true` → `false`（即時性重視、Batch API 待ちなし）
- 話者ラベルは保持（例: `SPEAKER_00: 自社 / SPEAKER_01: 顧客` → `ch0: 自社 / ch1: 顧客`）

> 💡 旧カセット名（`live_sales` / `live_internal` / `one_on_one_live`）は deprecation 警告付きで自動マッピングされるため、既存のコマンドもそのまま動きます。

### 選び方のコツ

- 録画ファイル処理 → 対応カセット名でそのまま
- その場で録音したい（マイク + アプリ音声）→ 同じカセット名 + `--live`
- 外部 SaaS に送りたくない（秘匿性高い）→ `one_on_one`
- 長時間セミナーで話者分離不要 → `seminar`（pyannote スキップで速い）
- 多人数ライブ MTG で pyannote を使いたい → `-c internal_meeting --live --override diarize.provider=pyannote --override input.mix=mono_merge`

---

## 5. 使い方 3 パターン

### 5.1 CLI でファイル 1 本

もっとも基本の使い方:

```bash
python -m cli.main /path/to/meeting.mp4 -c sales_meeting
```

内部で行われること:
1. 音声抽出 + 前処理（16kHz mono WAV 化）
2. 文字起こし（faster-whisper large-v3、10〜30 分）
3. 話者分離（pyannote 3.1、2〜5 分）
4. 用語補正（TERM_DICT で SaaS / iDeCo 等）
5. Claude で整形（フィラー除去 + 句読点挿入）
6. Claude で議事録抽出（商談タイトル・要約・ネクストアクション）
7. Markdown / JSON / SRT 出力
8. カセット指定の各 destination に配信

完了時の出力例:
```
[1/7] preprocess (provider=None) ...
[2/7] transcribe (provider=faster_whisper_batch) ...
[3/7] diarize (provider=pyannote) ...
...
Summary for run_id=20260423_143022_meeting
  Input:        /path/to/meeting.mp4
  Segments:     142
  Outputs:      ['md', 'json', 'srt']
  [preprocess] 15.2s
  [transcribe] 720.4s
  [diarize] 120.8s
  Claude total: in=12500 out=2800  (est. $0.0265)
```

### 5.2 CLI で複数ファイル一括処理

ディレクトリ内の全音声ファイルを順に処理:

```bash
python -m cli.main ./recordings/ -c sales_meeting --batch -o ./output/
```

1 ファイルが失敗しても次のファイルへ進みます（最後に成功 N / 失敗 M のサマリ）。

### 5.3 Streamlit Web UI

ブラウザから使いたい、非エンジニアメンバーに渡したい場合:

```bash
# ローカル 1 人用（認証なし）
streamlit run web/streamlit_app.py

# チーム共有用（ID/PW 認証あり）
export AUTH_MODE=basic
export AUTH_USERS="alice:xxxx:admin,bob:yyyy:user"
streamlit run web/streamlit_app.py --server.address 0.0.0.0
```

`http://localhost:8501` にアクセスすると以下が使えます:
- **Run**: ファイルアップロード → カセット選択 → 実行 → md ダウンロード
- **Live**: マイク+システム音声の録音 → 擬似リアルタイム字幕
- **History**: 過去ジョブの一覧、再ダウンロード、削除
- **Cassettes** (admin のみ): カセット YAML の閲覧

詳細: [SETUP_STREAMLIT.md](./SETUP_STREAMLIT.md)

---

## 6. 出力ファイルの見方

ジョブ完了後、以下の場所に成果物が保存されます:

```
output/
└── 20260423_143022_meeting/     ← run_id ディレクトリ
    ├── meeting_clean.wav          ← 前処理済み WAV（再利用可）
    ├── meeting.md                 ← 議事録 Markdown（メイン）
    ├── meeting_data.json          ← segments 生データ
    ├── meeting.srt                ← 字幕ファイル（動画用）
    ├── checkpoints/               ← 各 Step の中間状態（--resume で使用）
    └── chunks/ または stream_chunks/  ← transcribe の作業ファイル
```

同時に、カセットの `destinations` に設定された場所にもコピーされます:
- `local` → `./output/sales/meeting.md` など
- `notion` → DB に新規ページ
- `slack` → 指定チャンネルに投稿
- `email` → 指定アドレスに送信
- `google_drive` → 指定フォルダにアップロード

### `meeting.md` の例（sales_meeting カセット）

```markdown
# 商談議事録 | Acme Inc. | 2026-04-23

## サマリ
- 顧客は既存ツールからの移行を検討中
- 予算は月額 $50k まで
- 次回 MTG で技術仕様の深堀り

## 参加者
- 自社: 山田、佐藤
- 顧客: John Smith

## 議事
[00:00:12] 自社: 本日はお時間ありがとうございます...
[00:01:45] 顧客: 現状 Salesforce を使っているのですが...
...

## ネクストアクション
- [ ] 佐藤: 技術 FAQ を送付（〜4/25）
- [ ] John: 社内稟議を回す（〜5/1）
```

---

## 7. シナリオ別の実践例

### 7.1 商談録画を議事録化して Notion と Slack に送る

```bash
python -m cli.main /path/to/商談_20260423.mp4 -c sales_meeting --speakers 2
```

- `--speakers 2` で話者数を 2 名に固定（精度↑）
- `sales_meeting.yaml` に Notion DB / Slack チャンネルが定義済なら自動配信
- 所要時間: 60 分録画で **合計 40〜60 分**（CPU 実行時）

### 7.2 社内 MTG （3〜5 人）を処理

```bash
python -m cli.main /path/to/weekly_meeting.mp4 -c internal_meeting -s 4
```

- 参加人数が分からなければ `--speakers` 省略で自動推定（min=2, max=6）
- Claude で「参加者名・議論のテーマ・決定事項」を構造化抽出

### 7.3 90 分セミナーを整形議事録に

```bash
python -m cli.main seminar_20260423.mp4 -c seminar
```

- 話者分離は既定でオフ（登壇者 1 名想定）→ 速い
- セミナー特化プロンプト（`prompts/cleanup_seminar.md`）でフィラー除去 + 章立て抽出

### 7.4 1on1 を完全ローカルで処理（外部送信ゼロ）

```bash
python -m cli.main /path/to/1on1.mp4 -c one_on_one
```

- `mode=local_llm` だが Claude API **テキストのみ**は使う（議事録抽出のため）
- 本当に完全ローカルにしたい場合は `--skip-claude` を追加:
  ```bash
  python -m cli.main /path/to/1on1.mp4 -c one_on_one --skip-claude
  ```
  → transcribe + diarize + term_correct のみ、Claude は一切使わない

### 7.5 ライブで 1on1 を録音（macOS + BlackHole）

事前に BlackHole + Multi-Output Device セットアップ済みの状態で:

```bash
# 60 分録音 → 終了後に議事録生成（live:// URI 自動検知で --live 不要）
python -m cli.main "live://duration=3600" -c one_on_one

# 明示 --live も同等
python -m cli.main "live://duration=3600" -c one_on_one --live
```

または Streamlit の Live ページから録音時間をスライダで指定。

### 7.6 複数ファイル一括（月次処理など）

```bash
# ./recordings/ 配下の mp4/m4a/mp3/wav を全部処理
python -m cli.main ./recordings/ -c sales_meeting --batch -s 2
```

### 7.7 擬似リアルタイム字幕が欲しい

```bash
python -m cli.main "live://duration=1800" -c sales_meeting \
    --override transcribe.provider=whisper_streaming
```

- `live://` URI で自動的に `--live` 相当が有効化（chunked 設定 → override で streaming に差替）
- LocalAgreement-2（1〜3 秒遅延）
- Streamlit Live ページが部分結果をライブ表示

---

## 8. 応用機能

### 8.1 カセットの一時的な上書き

`--override KEY=VAL` で YAML を触らずに設定変更:

```bash
# モデルを turbo に変更（速さ優先）
python -m cli.main file.mp4 -c sales_meeting \
    --override transcribe.params.model=large-v3-turbo

# 話者数を 3 に固定
python -m cli.main file.mp4 -c sales_meeting --speakers 3
# （上記は --override diarize.params.num_speakers=3 のエイリアス）

# 複数上書き
python -m cli.main file.mp4 -c sales_meeting \
    --override transcribe.params.beam_size=3 \
    --override preprocess.params.noise_reduce_strength=0.5
```

### 8.2 失敗したジョブを途中から再開（resume）

長尺音声で Claude API エラーや通信断で止まった場合:

```bash
# 最初の実行（途中で失敗）
python -m cli.main long_meeting.mp4 -c seminar
# => 30 分 transcribe 済、llm_cleanup でエラー、run_id = 20260423_150000_long_meeting

# checkpoint から再開
python -m cli.main long_meeting.mp4 -c seminar --resume 20260423_150000_long_meeting
```

完了済み Step はスキップされ、llm_cleanup から再実行。

### 8.3 構成確認だけしたい（dry-run）

```bash
python -m cli.main file.mp4 -c sales_meeting --dry-run
```

実行せずにカセットの Step・destination を表示。

### 8.4 Modal GPU で高速化（任意、月 $3〜5 目安）

60 分以上の長尺で CPU 実行が辛いとき:

```bash
# 初期セットアップ（1 回のみ）
pip install modal
modal token new
modal secret create meeting-hub-secrets HUGGINGFACE_TOKEN=... ANTHROPIC_API_KEY=...
modal deploy scripts/modal_deploy.py

# カセットで transcribe だけ Modal 実行
python -m cli.main long.mp4 -c sales_meeting \
    --override transcribe.runtime=modal \
    --override diarize.runtime=modal
```

- transcribe が **約 10 倍高速**（60 分 → 2〜3 分）
- Modal Starter 無料枠 $30/月 で 20 件程度処理可能
- 詳細: [SETUP_MODAL.md](./SETUP_MODAL.md)

### 8.5 Claude Batch API で 50% 割引

カセットの `llm.batch_mode: true` が既定の商談・社内MTG・セミナーでは、**2 チャンク以上の長尺音声で自動的に Batch API**（中央値 5 分待ち、50% 割引）に切り替わります。1on1 は即時性重視で `batch_mode: false`。

---

## 9. 議事録を Notion / Slack / メール / Drive に送る設定

### 9.1 Notion 配信

1. Notion で議事録用 DB を 4 種作成（商談 / 社内 / セミナー / 採用）
2. [Notion Integration](https://www.notion.so/profile/integrations) で新規アプリ作成 → API key 取得
3. 各 DB を Integration と「接続」
4. `.env` に設定:
   ```
   NOTION_API_KEY=secret_xxx
   NOTION_DB_SALES=<DB ID>
   NOTION_DB_INTERNAL=<DB ID>
   NOTION_DB_SEMINAR=<DB ID>
   NOTION_DB_RECRUITING=<DB ID>
   ```
5. DB のプロパティ名とカセット YAML の `destinations[type=notion].properties` を合わせる（既定で `Title`, `Date`, `Summary` などを想定）

### 9.2 Slack 配信

1. [Slack App](https://api.slack.com/apps) で新規 App 作成
2. `Bot Token Scopes` に `chat:write` と `files:write` 追加
3. ワークスペースにインストール → `Bot User OAuth Token` 取得
4. 配信したいチャンネルに Bot を招待（`/invite @your-bot`）
5. `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx
   ```
6. カセット YAML の `destinations[type=slack].channel` を `#sales-minutes` など実チャンネル名に

### 9.3 メール配信（Gmail SMTP）

1. Gmail アカウントの 2 段階認証を有効化
2. [アプリパスワード](https://myaccount.google.com/apppasswords) を生成（16 文字）
3. `.env`:
   ```
   GMAIL_USER=your.name@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   ```
4. カセット YAML の `destinations[type=email].to` に送信先リストを記載

### 9.4 Google Drive アップロード

1. GCP プロジェクトで Drive API 有効化
2. サービスアカウント作成 → JSON 鍵を DL
3. `./secrets/sa.json` として配置（gitignore 対象）
4. Drive で共有フォルダを作り、**サービスアカウントのメールアドレス**（`xxx@xxx.iam.gserviceaccount.com`）を「閲覧者」or「編集者」で共有
5. `.env`:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=./secrets/sa.json
   ```
6. カセット YAML の `destinations[type=google_drive].folder_path` に `drive-folder://<フォルダ ID>` 形式で指定

---

## 10. プライバシーモードの使い分け

各カセットに `mode` が設定されており、通信先が制限されます。

| mode | 外部音声API | Claude API | Modal GPU | 使いどころ |
|---|:---:|:---:|:---:|---|
| `local` | ✕ | ✕ | ✕ | 完全ローカル、外部通信ゼロ |
| `local_llm` | ✕ | ◯（テキストのみ） | ✕ | 音声は外に出さず、テキスト整形だけ Claude |
| `cloud_batch` | ✕ | ◯ | ◯ | 録画バッチ処理、GPU 加速 OK |
| `cloud` | ◯ | ◯ | ◯ | 全機能解禁（本ツールでは採用カセットなし） |

**1on1 / 採用面談は `local_llm` 固定**です。これは音声が BlackHole 経由でも社外サーバに行かないことを保証します。意図的に変更しない限り、この設計は崩れません。

---

## 11. コスト感

実測値の目安（60 分の会議、チーム月 20 件想定）:

| 項目 | 料金 | 備考 |
|---|---|---|
| Whisper / pyannote | **無料** | ローカル or Modal 無料枠 |
| Claude Haiku 4.5 | **$0.02〜0.05 / 回** | in=$1/Mtok, out=$5/Mtok、Batch API で 50% 割引 |
| Modal Labs | **$0〜$5 / 月** | Starter 無料枠 $30/月 内で 20 件程度 |
| Google Drive / Notion / Slack | **既存契約のみ** | 追加費用なし |

**月額合計**: **$1〜$5 程度**（20 件処理、Modal 有無で変動）

post-hook で `Claude total: in=X out=Y  (est. $Z)` が毎回ログに出るので、累積確認できます。

---

## 12. トラブルシューティング

### `pip install` のあと `dependency conflicts` と表示される
- **まず**ログ末尾付近に `Successfully installed` があるか確認する。あれば多くの場合 **インストールは成功**しており、表示は **既存パッケージとの不整合の警告**です。
- **対処**: §3.1 のとおり **新しい venv** を作り、その中だけに `requirements.txt` を入れる。グローバル環境に Prophet / Stan / 古い PyTorch 周辺が混在していると、`torchvision` と `torch`、`httpstan` と `numpy` などの組み合わせで警告が出やすいです。
- meeting-hub 本体は **`torchvision` を要求しません**。別用途で必要なら、torch のバージョンに合わせて `torchvision` を入れ直すか、用途ごとに環境を分けてください。

### Streamlit 起動時に `no attribute 'Icicle'`（plotly）
古い **plotly** が残っていると、Streamlit が Plotly テーマを初期化するときに `plotly.graph_objs.layout.template.data` に `Icicle` がなく **`AttributeError`** になります。**対処**: `pip install 'plotly>=5.0'`（`requirements.txt` に同梱済み）。そのうえで `pip install -r requirements.txt` をやり直すか venv を新規作成してください。

### `HUGGINGFACE_TOKEN is required for pyannote diarize`
pyannote モデルに Hugging Face でアクセス許可していない、または `.env` に TOKEN 未設定。§3.3 / §3.4 を参照。

### `ANTHROPIC_API_KEY is not set`
`.env` に key がないか、`source .env` を忘れている。Streamlit から起動する場合は `.env` が自動ロードされる。

### 話者分離の精度が低い
- `--speakers N` で人数を明示指定
- `--override diarize.params.segmentation_threshold=0.35` で感度を上げる
- 2ch 録音なら `live_*` カセット（channel_based）に切替

### セグメント 0 件で止まる
- 音量が低すぎる可能性 → `--override preprocess.params.loudnorm="I=-16:TP=-1.5:LRA=11"`
- 無音区間が長すぎる可能性 → VAD リトライが自動で走る（`--override transcribe.params.retry_vad_threshold=0.2`）

### Whisper がハルシネーションを出力（「ご視聴ありがとう」等）
7 パターンの自動除去が既に動作。追加したい場合:
```bash
--override transcribe.params.hallucination_patterns='["^ご視聴", "^お楽しみください"]'
```

### Claude の JSON parse エラーが出た
既に 1 回自動リトライする。それでも失敗するなら:
```bash
--override minutes_extract.params.use_structured_output=true
```
で tool_use による 100% JSON 保証モードに。

### 処理が長すぎる
- `--override transcribe.params.model=large-v3-turbo` で速度優先
- Modal 利用（§8.4）で GPU 実行

### Streamlit 起動するが画面が真っ白
ブラウザキャッシュクリア、または `streamlit cache clear` 実行。

### `--resume` で「No checkpoint found」
- `output/` 配下に指定した run_id のディレクトリがあるか確認
- checkpoint は最低 1 Step 完了後に作られる

### メール送信で 535 エラー
- Gmail アプリパスワードが 16 文字（スペースあり or なし）で正しいか再確認
- 2 段階認証が有効になっているか確認

---

## 13. FAQ

**Q. Zoom 会議をそのまま録音できますか？**
A. はい。macOS なら BlackHole + Multi-Output Device、Windows なら VoiceMeeter で Zoom 音声 + マイクを 2ch に合成して `live_*` カセットで取り込みます。Zoom SDK の直接統合は現在保留中です。

**Q. 会議の途中から録音を開始できますか？**
A. CLI ならできません（事前に duration を指定）。Streamlit Live ページでは停止ボタン実装なしで、指定時間経過で自動停止します。途中停止対応は今後の改善候補。

**Q. 英語の会議も使えますか？**
A. カセット YAML の `transcribe.params.language` を `en` に変更すれば OK。ただし prompts/*.md は日本語向けなので、英語会議用のプロンプトを別途作成することを推奨。

**Q. 複数の会社で使い回すとき、専門用語辞書はどう管理しますか？**
A. `vocab/terms/` に会社別 YAML を置き（例: `company_acme.yaml`）、カセットで `terms.stack: [business, it, company_acme]` と指定。後勝ちで上書きされます。

**Q. 議事録のテンプレをカスタマイズしたい**
A. `templates/<cassette>.md.j2` を編集。Jinja2 構文で `{{ minutes.summary_3lines }}` 等の変数を差し替えられます。

**Q. どのくらいの長さまで処理できますか？**
A. 実用上 **3 時間まで**は問題なく動作（テスト済）。それ以上は Claude の context window 超過リスクがあるので分割推奨。

**Q. チームメンバー全員に Streamlit サーバを立てる必要がありますか？**
A. いいえ。1 台のサーバで `--server.address 0.0.0.0` + BasicAuth で共有すれば OK。または Phase 3 完了後のジョブ履歴機能で個人別に管理可能。

**Q. 既存の文字起こしツール（transcription-pipeline / seminar-transcription）から乗り換えるには？**
A. `docs/PHASE2_COMPLETION.md §4.1 コマンド対応表` を参照。概ね `python run.py X` が `python -m cli.main X -c sales_meeting` に置き換わります。

---

## 関連ドキュメント

- [README.md](../README.md) — プロジェクト概要・開発者向け情報
- [docs/FLOW.md](./FLOW.md) — 処理フロー図（7 Step の詳細、モード別分岐、data flow）
- [docs/SETUP_LIVE_AUDIO_MACOS.md](./SETUP_LIVE_AUDIO_MACOS.md) — BlackHole セットアップ
- [docs/SETUP_LIVE_AUDIO_WINDOWS.md](./SETUP_LIVE_AUDIO_WINDOWS.md) — VB-Cable セットアップ
- [docs/SETUP_STREAMLIT.md](./SETUP_STREAMLIT.md) — Web UI 起動手順
- [docs/SETUP_MODAL.md](./SETUP_MODAL.md) — Modal Labs GPU 実行
- [docs/SETUP_ZOOM_SDK.md](./SETUP_ZOOM_SDK.md) — Zoom SDK 対応（保留中）
- [docs/PHASE0_DESIGN.md](./PHASE0_DESIGN.md) — プライバシー設計の詳細
- [docs/ROADMAP.md](./ROADMAP.md) — 機能ロードマップ

---

## サポート

- ツール不具合・機能要望: `meeting-hub` リポジトリに Issue を起票
- 運用上の質問: チーム Slack `#meeting-hub-support` チャンネル（内部運用時）

**最終更新**: 2026-04-27（venv / pip 警告 / plotly と Streamlit の追記）
