# Phase 3 完了レポート

> **目的**: `meeting-hub` Phase 3（Web UI + Modal + Batch API + ジョブ履歴）の完了判定資料。

---

## 1. 完了チェックリスト

- [ ] Streamlit で file upload → cassette 選択 → 実行 → md DL が E2E 動作
- [ ] ジョブ履歴が保存・閲覧・再DL できる
- [ ] `runtime: modal` の Step が Modal 上で動作（transcribe で実証）
- [ ] Claude Batch API が `cloud_batch` + `batch_mode: true` で有効化
- [ ] Modal 無料枠内（$30/月）で 20 件処理の実測（ユーザー実施）
- [ ] BasicAuth で管理者 / 一般の 2 層が機能
- [ ] `docs/PHASE3_COMPLETION.md` の承認

---

## 2. 実装サマリ

### 2.1 M12: 履歴 + 認証
- `core/history.py` — SQLite (WAL)、jobs + step_events テーブル
- `web/auth.py` — `NoAuth` / `BasicAuth` / `GoogleSSO`(skeleton)、`User(id, name, role)`
- env: `AUTH_MODE` / `AUTH_USERS`

### 2.2 M13: Streamlit Web UI
- `web/streamlit_app.py` — サイドバーで Run / History / Cassettes 切替
- `web/run_service.py` — 別スレッドで `Pipeline.run` を走らせ、history に記録
- `.streamlit/config.toml` — `maxUploadSize=500MB`
- 進捗: checkpoint poll + Step events 表示

### 2.3 M14: Modal ランタイム
（Phase 6 リファクタで `core/runtime.py` 単一モジュールに統合済）
- `RuntimeAdapter` ABC + `register_runtime` / `get_runtime`
- `LocalRuntime` — 現在のプロセスで `step.process(ctx)`
- `ModalRuntime` — Modal 関数を lookup、bytes で音声送信、結果 segments を受信
- `scripts/modal_deploy.py` — `transcribe_on_modal` / `diarize_on_modal` を A10G GPU で deploy
- `Pipeline` を `StepConfig.runtime` 対応に改修
- `docs/SETUP_MODAL.md` に手順

### 2.4 M15: Claude Batch API
- `ClaudeClient.complete_batch(system, user_contents)` 新規
- `messages.batches.create` → polling (15秒間隔) → `batches.results`
- `llm_cleanup` Step が `cassette.llm.batch_mode` + `mode=cloud_batch` かつ chunk>=2 で自動切替
- 失敗時は messages API に fallback + warning

### 2.5 M16: 進捗表示 + ジョブ履歴 UI
- `Pipeline.on_step_start` / `on_step_complete` フック
- `RunService` が Step events を history に記録
- Streamlit History ページで step events + elapsed を表示

### 2.6 M17: 仕上げ
- `docs/SETUP_MODAL.md` / `docs/SETUP_STREAMLIT.md` / `docs/PHASE3_COMPLETION.md`
- `GoogleSSOProvider` スケルトン（Phase 3.5 で本実装）

---

## 3. テスト実績（Phase 3 時点）

```
tests/unit/core/         — +14件 (history, runtime, claude_batch)
tests/unit/web/          — +12件 (auth, run_service)
tests/integration/       — 既存継続

小計: 新規 26 件追加、既存と合わせて 120+ tests 全 PASS
```

---

## 4. 運用ガイド

### 4.1 チームで使い始める最短手順

```bash
# 1. リポクローン + 依存
git clone <meeting-hub>
cd meeting-hub
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. 秘密情報
cp .env.example .env
# HUGGINGFACE_TOKEN / ANTHROPIC_API_KEY / GMAIL_* / SLACK_BOT_TOKEN / NOTION_API_KEY / GOOGLE_APPLICATION_CREDENTIALS

# 3. 認証
export AUTH_MODE=basic
export AUTH_USERS="alice:xxxx:admin,bob:yyyy:user"

# 4. Web UI
streamlit run web/streamlit_app.py
```

### 4.2 Modal を使いたい場合（transcribe/diarize のみ）

```bash
pip install modal
modal token new
modal secret create meeting-hub-secrets HUGGINGFACE_TOKEN=... ANTHROPIC_API_KEY=...
modal deploy scripts/modal_deploy.py

# カセットで runtime: modal を指定（推奨: 長尺音声のみ）
```

### 4.3 Batch API を使いたい場合（llm_cleanup）

カセット YAML で:
```yaml
mode: cloud_batch
llm:
  batch_mode: true
```

2 チャンク以上あれば Batch API が自動利用される（50%割引）。

---

## 5. 既知の制約（Phase 4 以降に持ち越し）

1. **擬似ストリーム/真リアルタイムなし** — Phase 4 で faster_whisper_chunked
2. **Zoom SDK 非対応** — Phase 5 optional
3. **Google SSO は skeleton** — Phase 3.5 で本実装
4. **Modal 実行の音声データ転送は bytes** — 大容量音声（>500MB）で Modal volume に移行検討
5. **Batch API polling はブロッキング** — UI は rerun で更新、Phase 4 で非同期化検討
6. **Streamlit は 1 プロセス前提** — 大規模運用時は FastAPI + Next.js に移行検討（PHASE0_DESIGN.md §5）

---

## 6. Phase 4 への申し送り

- `transcribe` に provider `faster_whisper_chunked` 追加（10〜30 秒チャンク処理）
- `core/streaming/buffer.py`（チャンク化バッファ）
- `core/streaming/pipeline.py`（非同期パイプライン）
- NeMo 話者分離の評価
- ライブカセット（`live_sales.yaml` 等）の追加

---

## 7. 切替ゴーサイン（承認欄）

```
□ Phase 3 完了レポート承認
□ Streamlit + Modal + Batch API が 1 週間の継続運用でエラーなし
□ ジョブ履歴が想定通り機能
□ `meeting-hub` に v0.3.0 タグ打ち

承認日: 2026-MM-DD
承認者:
```
