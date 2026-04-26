# Hugging Face Spaces デプロイ手順

> **想定構成**: HF Spaces (CPU Basic, 16GB RAM, 完全無料) + Modal Labs ($30/月クレジット内)
> **想定時間**: 初回 2〜3 時間（HF / Modal アカウント未取得の場合）、再 deploy は git push のみ
> **前提**: GitHub `sato-tech/meeting-hub` リポジトリが Public で公開済（既に完了）

このリポジトリには HF Spaces 用の以下のファイル・設定が**既に実装済**です:
- `requirements.txt`（軽量、HF Spaces 互換）
- `requirements-ml.txt`（重い ML 依存、ローカル / Modal 用）
- `packages.txt`（apt: ffmpeg）
- `.streamlit/config.toml`（maxUploadSize=500MB）
- `core/cassette.py`: `MEETING_HUB_FORCE_MODAL` env で transcribe/diarize を Modal に強制
- `core/runtime.py`: forced 時のフォールバック禁止（fail-loud）
- `.github/workflows/sync-to-hf-spaces.yml`: main push で自動同期

ユーザー側で実施するのは以下の手動ステップのみです。

---

## 0. 全体の流れ

```
1. Modal アカウント作成 + API key 用 Secret 作成 + scripts/modal_deploy.py を deploy
2. Hugging Face アカウント作成 + meeting-hub Space を作成（空でOK）
3. HF Personal Access Token 発行
4. GitHub repo Secrets に HF_USERNAME / HF_TOKEN / HF_SPACE_NAME を設定
5. GitHub Action 起動（push or workflow_dispatch）→ HF Spaces に自動同期
6. HF Spaces Settings → Variables and secrets で AUTH_USERS 等を設定
7. ブラウザで https://huggingface.co/spaces/<your>/meeting-hub にアクセス
8. BasicAuth でログイン → 短い音声で E2E テスト
```

---

## 1. Modal セットアップ（先に GPU 関数を deploy）

### 1.1 アカウント作成 & CLI 認証

```bash
# ローカルで実行
pip install modal
modal token new
# ブラウザが開く → Modal にサインアップ（GitHub 連携が最速）→ 認証完了
```

### 1.2 Secret 登録（HF / Anthropic キーを Modal 側に保管）

```bash
modal secret create meeting-hub-secrets \
    HUGGINGFACE_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
    ANTHROPIC_API_KEY="sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 1.3 Modal 関数を deploy

```bash
modal deploy scripts/modal_deploy.py
```

成功時の出力例:
```
✓ Created secret meeting-hub-secrets
✓ App deployed in 12.3s 🎉

App created: https://modal.com/apps/<your-username>/main/meeting-hub
Functions:
  • transcribe_on_modal
  • diarize_on_modal
```

### 1.4 動作確認（任意）

```bash
modal app list   # meeting-hub が ✓ で出れば OK
```

---

## 2. Hugging Face Space を作成

### 2.1 アカウント

https://huggingface.co/join で無料アカウント作成（メール認証）

### 2.2 Space 作成

https://huggingface.co/new-space で以下を設定:

| 項目 | 値 |
|---|---|
| Owner | あなたのアカウント |
| Space name | `meeting-hub`（任意） |
| Short description | 文字起こし → 話者分離 → AI 議事録抽出 |
| License | MIT |
| Space SDK | **Streamlit** |
| Streamlit SDK version | 1.35.0 |
| Hardware | **CPU basic — 2 vCPU, 16 GB**（無料） |
| Storage | None（後で追加可、SQLite なら不要） |
| Visibility | **Public**（Pro なら Private 可） |

→ "Create Space" をクリック。空の Space が作られます（README だけ）。

### 2.3 Personal Access Token 発行

https://huggingface.co/settings/tokens で:

1. **New token** をクリック
2. Name: `github-actions-meeting-hub`
3. Type: **write** （must be write — read だけでは push できない）
4. **Generate token** → 表示された `hf_xxxxx` をコピー（再表示不可、メモ必須）

---

## 3. GitHub repo に Secrets を設定

GitHub の `sato-tech/meeting-hub` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|---|---|
| `HF_USERNAME` | あなたの HF ユーザー名（例: `sato-tech`） |
| `HF_TOKEN` | §2.3 で発行した `hf_xxxxx` |
| `HF_SPACE_NAME` | §2.2 で付けた Space 名（例: `meeting-hub`） |

---

## 4. GitHub Action で HF Spaces に同期

### 4.1 自動 trigger（main 更新時）

`main` ブランチに何か push すれば自動的に `.github/workflows/sync-to-hf-spaces.yml` が走ります。

### 4.2 手動 trigger（初回はこれが早い）

GitHub の Actions タブ → **Sync to Hugging Face Spaces** → **Run workflow** → main を選択 → 緑ボタン。

成功すると HF Spaces に main の内容がコピーされ、HF 側で Streamlit のビルドが始まります（5〜10 分）。

### 4.3 ビルド確認

`https://huggingface.co/spaces/<HF_USERNAME>/meeting-hub` を開き、**Logs** タブで以下を確認:

```
==> Reading repository
==> Installing apt packages from packages.txt
    ffmpeg ✓
==> Installing Python packages from requirements.txt
    streamlit ✓ anthropic ✓ modal ✓ ...
==> Starting Streamlit app: web/streamlit_app.py
==> Application is running on port 7860
```

エラーが出る場合は §8 トラブルシューティング参照。

---

## 5. HF Spaces に Secrets を設定

Space ページ → **Settings** → **Variables and secrets**

### 5.1 Variables（公開可能、ログにも出る）

| Name | Value | 説明 |
|---|---|---|
| `AUTH_MODE` | `basic` | BasicAuth 有効化 |
| `MEETING_HUB_FORCE_MODAL` | `true` | transcribe/diarize を強制的に Modal で実行 |
| `MEETING_HUB_MODAL_APP` | `meeting-hub` | §1.3 で deploy した app 名 |
| `MEETING_HUB_OUTPUT_DIR` | `/data/output` | persistent storage を使う場合 |
| `MEETING_HUB_HISTORY_DB` | `/data/history.db` | 同上 |

### 5.2 Secrets（暗号化、ログには出ない）

| Name | Value | 説明 |
|---|---|---|
| `AUTH_USERS` | `alice:xxxxxxxx:admin,bob:yyyyyyyy:user,...` | 許可ユーザー一覧（自動生成パスワード） |
| `ANTHROPIC_API_KEY` | `sk-ant-api03-xxxxx...` | Claude API key（HF Spaces 側でも `llm_cleanup` / `minutes_extract` を実行するため必要） |
| `HUGGINGFACE_TOKEN` | `hf_xxxxx...` | 一応設定（直接は使わないが pyannote 関連で参照される可能性あり） |
| `MODAL_TOKEN_ID` | （Modal CLI で自動生成された ID） | HF Spaces から Modal 関数を呼ぶ認証 |
| `MODAL_TOKEN_SECRET` | （Modal CLI で自動生成された secret） | 同上 |

#### MODAL_TOKEN_ID / MODAL_TOKEN_SECRET の取得

```bash
cat ~/.modal.toml
```

```toml
[tokens]
token_id = "ak-xxxxxxxxxxxxxxxxxxxxxxxxxx"
token_secret = "as-xxxxxxxxxxxxxxxxxxxxxxxxxx"
```

このうち `token_id` と `token_secret` を HF Secrets に設定。

#### AUTH_USERS のパスワード生成

```bash
python -c "import secrets; print(','.join(f'{u}:{secrets.token_urlsafe(12)}:{r}' for u,r in [('alice','admin'),('bob','user'),('carol','user')]))"
```

出力例:
```
alice:Xx9aBcDeFgHi:admin,bob:Yy0pQrStUvWx:user,carol:Zz1mNoPqRsTu:user
```

これをコピーして `AUTH_USERS` Secret に貼り付け。**ユーザー本人にもパスワードを伝える**ことを忘れずに。

### 5.3 Secrets 反映

Secrets を変更すると HF Spaces は自動で **Restart** します（30 秒〜1 分）。Logs タブで再起動完了を確認。

---

## 6. アクセス確認

ブラウザで `https://huggingface.co/spaces/<HF_USERNAME>/meeting-hub` を開く:

1. ログイン画面が表示される
2. AUTH_USERS で設定した username / password を入力
3. メイン画面が表示される
4. **Run** ページで短い音声（30 秒〜1 分）をアップロード
5. カセット選択 → **▶ 実行**
6. 進捗ログを確認:
   - `[1/7] preprocess (provider=simple) ...` ← HF Spaces 内で実行
   - `[2/7] transcribe (provider=faster_whisper_batch, runtime=modal) ...` ← Modal GPU で実行
   - `[3/7] diarize (provider=pyannote, runtime=modal) ...` ← 同上
   - `[4/7] term_correct (provider=regex) ...` ← HF Spaces 内
   - `[5/7] llm_cleanup (provider=claude) ...` ← HF Spaces から Claude API
   - `[6/7] minutes_extract (provider=claude) ...` ← 同上
   - `[7/7] format (provider=default) ...` ← HF Spaces 内
7. md / json / srt のダウンロードボタンが表示されたら成功

---

## 7. 利用者への共有

URL とログイン情報をチームに共有:

```
URL:   https://huggingface.co/spaces/sato-tech/meeting-hub
User:  alice    Password: Xx9aBcDeFgHi    Role: admin
User:  bob      Password: Yy0pQrStUvWx    Role: user
User:  carol    Password: Zz1mNoPqRsTu    Role: user

注意:
- 48 時間アクセスがないと Space が sleep します（再起動 30 秒）
- 同時 2 人以上での重い処理は Modal キューで順次実行されます
- アップロードは最大 500MB（90 分の mp4 まで）
- 議事録は History ページから後で再ダウンロード可能
```

---

## 8. トラブルシューティング

### `gh run list --workflow=sync-to-hf-spaces.yml` が `HTTP 404: workflow ... not found on the default branch`

GitHub の REST API は **`--workflow` にファイル名を渡すとき、既定ブランチ（多くは `main`）にその YAML が存在する**ことを要求します。次を順に確認してください。

1. **ローカルで未コミット** — `.github/workflows/sync-to-hf-spaces.yml` が `git status` で Untracked のままだと、リモートに無く 404 になります。`git add .github/workflows/sync-to-hf-spaces.yml` → commit → push。
2. **まだ `main` に入っていない** — フィーチャーブランチだけにワークフローがある場合も同様です。**`main` にマージ**（または `main` へ直接 push）してから再度 `gh run list --workflow=sync-to-hf-spaces.yml` を実行。
3. **リポジトリの取り違え** — `gh repo set-default` やカレントディレクトリが `sato-tech/meeting-hub` になっているか確認。

ワークフロー名を指定せず全体を見る場合: `gh run list -L 5`（ブランチ上の実行履歴は出ますが、ワークフロー YAML が default に無いと `--workflow=` だけは 404 のままです）。

### `requirements.txt` インストールでエラー

HF Spaces のログで `Installing torch...` が出ていれば、`requirements-ml.txt` の中身が混入している可能性。`requirements.txt` を再確認（slim 版になっているか）。

### `MEETING_HUB_FORCE_MODAL is set, but Modal function for step='transcribe' is not available`

Modal 側の deploy が失敗 or `MEETING_HUB_MODAL_APP` の値が違う:

```bash
# ローカルで確認
modal app list
# meeting-hub が出ているか、app 名が一致しているか
```

### 認証画面が出ない（誰でもアクセスできる）

`AUTH_MODE=basic` が Variables に設定されていない。Settings → Variables を再確認。

### Streamlit が起動しない（Logs で `ModuleNotFoundError`）

軽量 `requirements.txt` から必要なものが漏れている。HF Spaces の Logs を見て、足りないパッケージを `requirements.txt` に追加して push。

### Modal の cold start が遅い

初回呼出は 30〜60 秒かかります（コンテナ起動 + モデル DL）。2 回目以降は 5〜10 秒で起動。warmup したい場合は Modal の `keep_warm` 設定を `scripts/modal_deploy.py` に追加。

### HF Spaces の容量超過

ジョブ履歴 DB と中間ファイルが永続的に貯まるため、月 1 回 `History` ページから古いジョブを削除すると安全。Persistent Storage 50GB を超えたら Pro 版にアップグレードするか、Notion / Drive 連携で外部保管に移す。

### 同時実行で OOM

CPU Basic は 16GB RAM。同時 2〜3 ジョブで Streamlit + ジョブメモリが圧迫されます。利用者が増えたら Pro Spaces ($9/月) で 32GB に上げるか、Spaces を 1 ジョブのみ受付に制限（実装は別途検討）。

---

## 9. 運用コスト目安

| 項目 | 月額 |
|---|---|
| HF Spaces (CPU Basic) | **$0** |
| Modal Labs（無料枠 $30 内） | **$0**（月 20-30 件処理目安） |
| Anthropic Claude API | $0.02-0.05/件 × 件数（Batch 50% 割引適用） |
| **合計** | **$0〜$5 / 月**（ライト利用） |

Pro 移行ライン:
- 月 100 件超え → Modal Pro $30 検討
- 利用者 5 名超え or Private 化したい → HF Spaces Pro $9
- 商用展開 → 自前 GPU or AWS Spot

---

## 10. 関連ドキュメント

- [docs/FREE_HOSTING_OPTIONS.md](./FREE_HOSTING_OPTIONS.md) — 他の無料ホスティング案との比較
- [docs/SETUP_MODAL.md](./SETUP_MODAL.md) — Modal Labs の詳細
- [docs/SETUP_STREAMLIT.md](./SETUP_STREAMLIT.md) — Streamlit ローカル起動
- [docs/USER_GUIDE.md](./USER_GUIDE.md) — 利用者向けガイド
