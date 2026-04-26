# 無料で本番リリースできるホスティング比較

> **生成日**: 2026-04-27
> **目的**: meeting-hub を**完全無料**で Web 上に本番リリースする選択肢を比較し、推奨構成を提示
> **対象**: チーム数名向けの社内/小規模 SaaS 運用想定

---

## 1. Executive Summary

1. **無料で本番運用できる現実解は 3 通り**（HF Spaces+Modal / Oracle Cloud Always Free / Streamlit Cloud+Modal）
2. **最有力は Hugging Face Spaces + Modal の二段構成** — 完全無料、既存 Modal 統合がそのまま活きる、HTTPS 自動、GitHub 連携
3. Streamlit Community Cloud 単独は 1GB RAM 制約で large-v3 が動かないため、ML は Modal に逃がす設計が必須
4. Oracle Cloud Always Free（4 OCPU + 24GB RAM ARM）は性能最強だが運用工数大、Linux 慣れ必須
5. Render Free / Fly.io / Railway は**実質無料ではない**（sleep 過酷 or 月額発生）

---

## 2. 比較表（meeting-hub 適合度）

| プラットフォーム | RAM/CPU | Sleep 挙動 | ストレージ | meeting-hub 適合 | 月額（基本） |
|---|---|---|---|:---:|---|
| **Hugging Face Spaces (CPU Basic)** | 16GB / 2vCPU | 48h アイドルで sleep | 50GB persistent | ★★★ | **$0** |
| Streamlit Community Cloud | 1GB / 1 CPU | 数日アイドルで sleep | 1GB | ★（large-v3 不可） | $0 |
| Render Free | 512MB / 0.1 CPU | **15min sleep** | 1GB | ✗ | $0 |
| Railway Trial | 8GB / 8vCPU | なし | 100GB | ★★★ | **$5 クレジット/月** |
| Fly.io | 任意 | なし | 任意 | — | 2025 〜実質有料 |
| Oracle Cloud Always Free | 24GB / 4 OCPU (ARM) | なし | 200GB | ★★★（要セルフ運用） | **$0 永久** |
| **Modal**（補助役） | A10G GPU | 関数呼出時のみ起動 | Volume 50GB | ★★★（GPU 専用） | **$30 クレジット/月** |
| AWS / GCP / Azure 無料枠 | t2.micro 1GB 等 | なし | 5〜30GB | ✗ | $0（12 ヶ月） |
| Vercel | サーバレス | 即起動 | KV あり | ✗（Streamlit 非対応） | $0 |

---

## 3. 🏆 最有力構成: Hugging Face Spaces + Modal

### アーキテクチャ図

```
┌─────────────────────────────────────────────────────────┐
│  ユーザーのブラウザ                                      │
│  https://huggingface.co/spaces/<your>/meeting-hub        │
└────────────────────┬───────────────────────────────────┘
                     │ HTTPS（自動）
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Hugging Face Spaces (CPU Basic、16GB RAM, $0)          │
│  ─────────────────────────────────────────────────────  │
│  - Streamlit Web UI（既存 web/streamlit_app.py）          │
│  - SQLite (jobs.db) は persistent storage に保存         │
│  - 軽量 Step:                                             │
│      preprocess (simple) / term_correct / format         │
│  - Claude API 直叩き Step:                                │
│      llm_cleanup / minutes_extract                       │
│  - BasicAuth で AUTH_USERS の指定ユーザー限定             │
└────────────────────┬───────────────────────────────────┘
                     │ Modal Function 呼出（既存 core/runtime.py）
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Modal Labs（A10G GPU、月 $30 クレジット内）              │
│  ─────────────────────────────────────────────────────  │
│  - transcribe_on_modal (faster-whisper large-v3)         │
│  - diarize_on_modal (pyannote 3.1)                       │
│  - 既に scripts/modal_deploy.py に実装済                 │
│  - Secrets: HF_TOKEN / ANTHROPIC_API_KEY                 │
└─────────────────────────────────────────────────────────┘
```

### この構成が最強な理由

1. **完全無料**（Spaces $0 + Modal $30 クレジット内 = 月 20〜30 件処理可能）
2. **既存実装そのまま使える** — Phase 3 で実装済の Modal 統合を `runtime: modal` で切り替えるだけ
3. **HTTPS 自動** + **GitHub 連携で git push deploy**
4. **Spaces persistent storage 50GB** — 出力 / 履歴 DB の永続化
5. **16GB RAM** — Spaces 側で軽量モデル（small/turbo）も動かせる柔軟性

### 制約

- **Public Space 必須**（Private は Pro $9/月）— ただしリポ自体は既に Public なので問題なし
- **48 時間アクセスなしで sleep**（再起動 30 秒）— チーム使用なら問題なし
- **カスタムドメイン不可**（Pro 限定）— `*.hf.space` URL は固定
- **アップロードサイズは Streamlit 設定依存**（既定 200MB → `.streamlit/config.toml` で 500MB に上げ済）

### 必要な追加作業

```yaml
# README.md の冒頭に YAML frontmatter を追加（HF Spaces 認識用）
---
title: meeting-hub
emoji: 🎙️
colorFrom: indigo
colorTo: purple
sdk: streamlit
sdk_version: "1.35.0"
app_file: web/streamlit_app.py
pinned: false
license: mit
---
```

具体作業（推定 2〜3 時間）:
1. README に上記 frontmatter を追加（HF Spaces が読む）
2. `requirements.txt` を Spaces 用に軽量化（torch / pyannote / faster-whisper を Modal 側のみに移し、Spaces 側は streamlit + anthropic + sqlite + jinja2 + python-dotenv 等のみ）
3. カセット既定値に `transcribe.runtime: modal` `diarize.runtime: modal` を追加（または env で制御）
4. HF Spaces 作成（GitHub からインポート）
5. Spaces の Settings → Secrets に `AUTH_USERS` / `ANTHROPIC_API_KEY` / `HUGGINGFACE_TOKEN` / `MEETING_HUB_MODAL_APP` を設定
6. Modal 側を `modal deploy scripts/modal_deploy.py` で deploy
7. アクセス確認

---

## 4. 🥈 代替案: Oracle Cloud Always Free

### 概要

```
- 永久無料: 4 OCPU + 24GB RAM ARM (Ampere A1) × 1 インスタンス
- ブロックストレージ: 200GB 永久無料
- 月 10TB 帯域、最大 50 同時接続まで OK
- リージョン: 東京 / 大阪 選択可能
```

### メリット
- 性能・自由度が最高（Streamlit + ML 全部セルフホストで完結）
- 月 $0 永久
- VM なので何でも動く（pyannote ローカル、Modal 不要）

### デメリット
- VM 運用工数大（ssh、ufw、systemd、nginx、certbot 等）
- ARM アーキテクチャなので一部 Python wheel が手動ビルド必要
- 登録時にクレジットカード必須（課金されないが心理的ハードル）
- リソース不足時の自動スケールなし

### 向いている人
- Linux 運用に慣れている
- 月額 $0 を絶対死守したい
- ML を全部セルフでやりたい（Modal 不要）

### セットアップ概略

```bash
# Oracle Cloud で VM 作成 → Ubuntu 22.04 ARM
ssh ubuntu@<public-ip>
sudo apt update && sudo apt install -y python3.11 python3-pip ffmpeg nginx certbot
git clone https://github.com/sato-tech/meeting-hub.git
cd meeting-hub
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt    # ARM では一部 wheel が無くソースビルド可能性あり
# ARM での既知の地雷: faster-whisper の CTranslate2 は ARM wheel あり、pyannote.audio も OK
nohup streamlit run web/streamlit_app.py --server.address 0.0.0.0 &
# nginx + certbot で HTTPS + custom domain
```

---

## 5. 🥉 最小工数案: Streamlit Community Cloud + Modal

### 概要

```
- Streamlit Cloud (無料、1GB RAM、自動 HTTPS、git 連携)
- ML は全部 Modal（large-v3 必須）
- 5 分で deploy 可能
```

### メリット
- セットアップ最速（GitHub 連携 → 即 deploy）
- 公式推奨パスでドキュメント豊富
- Streamlit 開発者の本拠地

### デメリット
- 1GB RAM はジョブ大量並列で苦しい（meeting-hub は同時 1 ジョブが現実的）
- カスタムドメイン不可
- Public リポなら無制限、Private は無料 1 つまで

### 必要な作業
1. https://streamlit.io/cloud で GitHub 連携
2. リポ・ブランチ・main file を選択（`web/streamlit_app.py`）
3. Secret に `AUTH_USERS` 等を設定
4. Deploy

**推定セットアップ工数**: 30 分〜1 時間

---

## 6. 候補外: なぜ Render / Fly.io / Vercel ではないか

| プラットフォーム | 不採用の理由 |
|---|---|
| **Render Free Web Service** | 512MB RAM では何も動かない、15min アイドル sleep |
| **Fly.io** | 2025 年から実質有料化（クレジット制） |
| **Railway** | 月 $5 クレジット = 実質有料（無料運用は数日で枯渇） |
| **Vercel** | サーバレス前提で Streamlit の WebSocket と相性悪 |
| **AWS Free Tier** | t2.micro 1GB RAM、12 ヶ月限定、ML 厳しい |
| **GCP Free Tier** | e2-micro 0.25GB、ほぼ何も動かない |
| **Azure Free** | B1S 1GB RAM、12 ヶ月限定 |
| **GitHub Pages + Actions** | Streamlit は WebSocket 必須、Pages は静的のみ |

---

## 7. ロールアウト戦略（無料 → 有料の段階移行）

| 段階 | 環境 | 月額 | タイミング |
|---|---|---|---|
| **Phase A: テスト** | HF Spaces + Modal | $0 | 1〜2 週間で全機能検証 |
| **Phase B: 安定運用** | 同上、月 100 件超えたら Modal 課金検討 | $0〜30 | 〜継続 |
| **Phase C: スケール** | HF Spaces Pro（Private + カスタムドメイン）+ Modal | $9〜39 | 利用者 10 名超え or 商用展開時 |
| **Phase D: 専有** | 自前 GPU サーバ or AWS Spot | $50〜 | 月 1000 件超え時 |

---

## 8. 詳細比較表（meeting-hub 特化）

| 観点 | HF Spaces + Modal | Oracle Free | Streamlit Cloud + Modal | Railway |
|---|:---:|:---:|:---:|:---:|
| 完全無料か | ◯ | ◯ | ◯ | ✗（$5〜） |
| Sleep なし | △ (48h) | ◯ | △ (数日) | ◯ |
| 24/7 動作 | △ | ◯ | △ | ◯ |
| ML 大モデル | ◯ (Modal) | ◯ (ARM) | ◯ (Modal) | ◯ |
| HTTPS 自動 | ◯ | △ (certbot) | ◯ | ◯ |
| GitHub 連携自動 deploy | ◯ | ✗ | ◯ | ◯ |
| カスタムドメイン | Pro のみ | ◯ | Pro のみ | ◯ |
| 既存 Modal 実装活用 | 高 | 中 | 高 | 高 |
| Auth 設定 | env Secret | 任意 | env Secret | env |
| セットアップ難易度 | **低** | 高 | **最低** | 中 |
| 運用工数 | **小** | 大 | **小** | 小 |

---

## 9. 推奨構成の段階的セットアップ手順（Phase A: HF Spaces + Modal）

### 9.1 事前準備

- Hugging Face アカウント（無料）
- Modal アカウント（無料、$30 クレジット付き）
- 既に GitHub に Public リポ `sato-tech/meeting-hub` がある状態

### 9.2 Modal 側のセットアップ（先に GPU 関数を deploy）

```bash
pip install modal
modal token new
modal secret create meeting-hub-secrets \
    HUGGINGFACE_TOKEN="hf_xxxxx" \
    ANTHROPIC_API_KEY="sk-ant-xxxxx"
modal deploy scripts/modal_deploy.py
# → transcribe_on_modal / diarize_on_modal が deploy される
```

### 9.3 Hugging Face Spaces の作成

```bash
# HF CLI（任意、Web UI でも可）
pip install huggingface_hub
huggingface-cli login

# Web UI: https://huggingface.co/new-space
#   - Owner: 自分のアカウント
#   - Space name: meeting-hub
#   - License: MIT
#   - SDK: Streamlit
#   - Hardware: CPU basic (free)
#   - Visibility: Public
```

### 9.4 リポ frontmatter 追加

```diff
# README.md の最上部に追加
+---
+title: meeting-hub
+emoji: 🎙️
+colorFrom: indigo
+colorTo: purple
+sdk: streamlit
+sdk_version: "1.35.0"
+app_file: web/streamlit_app.py
+pinned: false
+license: mit
+---
+
 # meeting-hub
 ...
```

### 9.5 Spaces ↔ GitHub 同期

選択肢 2 つ:

**方法 A: HF Spaces を GitHub から手動 push**
```bash
git remote add hf https://huggingface.co/spaces/<username>/meeting-hub
git push hf main
```

**方法 B: GitHub Actions で自動同期**（推奨）
```yaml
# .github/workflows/sync-to-hf.yml
name: Sync to Hugging Face Spaces
on:
  push:
    branches: [main]
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: |
          git remote add hf https://USERNAME:${{ secrets.HF_TOKEN }}@huggingface.co/spaces/USERNAME/meeting-hub
          git push hf main --force
```

### 9.6 Spaces Settings に Secrets 設定

HF Spaces の Settings → Repository secrets:

```
AUTH_MODE=basic
AUTH_USERS=alice:xxxxxxxx:admin,bob:yyyyyyyy:user,carol:zzzzzzzz:user
ANTHROPIC_API_KEY=sk-ant-xxxxx
HUGGINGFACE_TOKEN=hf_xxxxx
MEETING_HUB_MODAL_APP=meeting-hub
MEETING_HUB_OUTPUT_DIR=/data/output
MEETING_HUB_HISTORY_DB=/data/history.db
```

### 9.7 requirements.txt の軽量化（Spaces 側）

```
# requirements.txt（Spaces 用に分離）
streamlit>=1.35
anthropic>=0.40.0
pydantic>=2.5
PyYAML>=6.0
jinja2>=3.1
python-dotenv>=1.0.0
modal>=0.64                # Modal 関数 lookup 用
notion-client>=2.2          # 必要なら
slack-sdk>=3.27             # 必要なら
google-api-python-client    # 必要なら
google-auth>=2.28.0
tqdm>=4.66.0
# 重い依存は Modal 側へ:
# faster-whisper, whisperx, pyannote.audio, librosa, noisereduce,
# soundfile, torch, torchaudio, scipy, sounddevice
```

local 開発用 / Modal deploy 用の重い依存は別ファイル `requirements-ml.txt` に切り出し。

### 9.8 カセット側の runtime 切替

env で全カセット強制 modal:

```bash
# Spaces Secret に追加
MEETING_HUB_FORCE_MODAL_RUNTIME=true
```

または個別カセット override:
```bash
# Spaces Secret に追加
MEETING_HUB_DEFAULT_OVERRIDES=transcribe.runtime=modal,diarize.runtime=modal
```

（既存実装に env 経由 override がない場合は cli/main.py に追加が必要）

### 9.9 動作確認

1. Spaces のビルドログを確認（Settings → Logs）
2. URL（`https://huggingface.co/spaces/<username>/meeting-hub`）にアクセス
3. BasicAuth でログイン
4. 短い音声（30 秒）を upload して E2E 確認
5. Modal の関数呼出が成功しているかログで確認

---

## 10. 既知のリスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| HF Spaces アイドル sleep | 48h 未使用で起動に 30 秒 | チーム共有なら問題ほぼなし |
| Modal $30 クレジット枯渇 | ML 処理が止まる | 月 100 件超えたら Pro $30 検討 |
| Public Space で URL が知られる | ブラウザに到達される | BasicAuth で認証必須にしてある |
| アップロード 200MB 上限 | 90 分動画は超える | `.streamlit/config.toml` で 500MB に上げ済 |
| 同時 2 ジョブで Spaces 16GB 圧迫 | 1 ジョブのみ受付推奨 | `RunService.start_job` でロック追加検討 |
| Modal cold start | 初回 30〜60 秒 | warmup 関数で対策可（Phase 6 案件） |

---

## 11. 結論

| 推奨度 | 構成 | 月額 | 工数 |
|---|---|---|---|
| **🏆 第 1 候補** | **HF Spaces + Modal** | $0 | 2〜3 時間 |
| 第 2 候補 | Oracle Cloud Always Free | $0 | 半日〜1 日 |
| 第 3 候補 | Streamlit Cloud + Modal | $0 | 30 分〜1 時間 |

**HF Spaces + Modal** が、無料・既存実装活用・運用工数バランスのすべてで最良。実機検証 1〜2 週間後、利用者 5 名超えなど安定運用フェーズで HF Spaces Pro $9 + Modal Pro $30 の組合せに移行する段階戦略を推奨。

---

## 関連ドキュメント

- [docs/USER_GUIDE.md](./USER_GUIDE.md) — ローカルセットアップ
- [docs/SETUP_MODAL.md](./SETUP_MODAL.md) — Modal Labs GPU 実行
- [docs/SETUP_STREAMLIT.md](./SETUP_STREAMLIT.md) — Streamlit Web UI 起動
- [docs/PHASE3_COMPLETION.md](./PHASE3_COMPLETION.md) — Modal 連携の実装詳細
- [docs/FLOW.md](./FLOW.md) — 処理フロー全体図

---

## 参考

- Hugging Face Spaces docs: https://huggingface.co/docs/hub/spaces
- Modal Labs docs: https://modal.com/docs
- Oracle Cloud Always Free: https://www.oracle.com/cloud/free/
- Streamlit Community Cloud: https://streamlit.io/cloud
