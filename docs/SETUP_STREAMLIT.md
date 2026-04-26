# Streamlit Web UI セットアップ

Phase 3 の Web UI を起動する手順。

## 1. 依存インストール

```bash
# 既存の venv で
pip install -r requirements.txt
# streamlit / modal / SQLite はここで入る
```

## 2. 環境変数設定（`.env`）

```bash
# 認証モード
AUTH_MODE=basic                              # noauth / basic / google のいずれか
AUTH_USERS=alice:secret:admin,bob:guest:user # basic のとき必須

# 出力ディレクトリ
MEETING_HUB_OUTPUT_DIR=./output

# ジョブ履歴 DB（既定: ~/.meeting-hub/history.db）
MEETING_HUB_HISTORY_DB=./data/history.db

# Phase 1+2 の env（HF / Claude / Notion / Slack / Gmail / GCP SA）は継続
```

## 3. 起動

```bash
streamlit run web/streamlit_app.py
```

ブラウザで `http://localhost:8501` にアクセス。

## 4. UI 操作フロー

1. **Login**: AUTH_MODE により NoAuth (名前のみ) / BasicAuth (user + password)
2. **Run ページ**:
   - カセット選択
   - `file upload` or `live audio`
   - `▶ 実行` で別スレッド起動
   - 完了後、md/json/srt/txt を DL 可能
3. **History ページ**:
   - 自分のジョブ一覧（admin は全員分を表示可能）
   - Step events（開始/完了の時刻・経過秒）を確認
   - 再 DL / 削除
4. **Cassettes ページ**（admin のみ）:
   - カセット YAML の閲覧

## 5. チーム共有サーバとして運用する場合

社内 LAN で共有する前提（外部公開しない）:

```bash
# サーバ側
export AUTH_MODE=basic
export AUTH_USERS="alice:xxxxx:admin,bob:yyyyy:user,carol:zzzzz:user"
streamlit run web/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

- `--server.address 0.0.0.0` で LAN 内の他マシンからアクセス可能
- 本番運用では reverse proxy (nginx + TLS) の前段を置き、社内 VPN からのみアクセスさせること
- Phase 3.5 で Google SSO 対応予定（`GoogleSSOProvider`）

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `Port 8501 is already in use` | 別プロセス（別 Streamlit や Docker が 8501 を公開している等）が占有中。`lsof -i :8501` で確認。いずれか: (1) 占有側を停止する、(2) 別ポートで起動する例: `streamlit run web/streamlit_app.py --server.port 8502` |
| Python 3.9 で Pydantic が「Unable to evaluate type annotation」（`str` と `None` の和型）を解釈できない | `pip install 'eval_type_backport>=0.2.0'`（`requirements.txt` に含む）。**推奨は Python 3.10+**（`pyproject.toml` の `requires-python` と一致）。 |
| アップロードサイズ上限に引っかかる | `.streamlit/config.toml` の `maxUploadSize` を増やす（既定 500MB） |
| 進捗が更新されない | 1 秒 poll している。ブラウザの rerun 抑止が効いていないか |
| Job 履歴が見えない | `MEETING_HUB_HISTORY_DB` のパスを確認、DB が初期化済か |
| ModuleNotFoundError: core | `streamlit run` の作業ディレクトリがリポルートか確認 |

## 関連

- `REPORT_PHASE3_PLAN.md`
- `web/streamlit_app.py`
- `web/auth.py` / `web/run_service.py`
- `core/history.py`
