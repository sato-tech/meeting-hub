# meeting-hub 処理フロー

CLI 起動から議事録配信までの内部動作を視覚化したドキュメントです。実装を追いたい開発者、カセット設計を把握したい運用者の参考資料として利用できます。

**最終更新**: 2026-04-23（Phase 5 + リファクタ + 精度改善 + ライブプロファイル統合後）

---

## 目次

1. [エンドツーエンド俯瞰](#1-エンドツーエンド俯瞰)
2. [7 Step の内部](#2-7-step-の内部pipeline_execute_steps)
3. [モード別の分岐](#3-モード別の分岐どこで何が変わるか)
4. [データ流（ctx 観点）](#4-データ流ctx-観点)
5. [外部配信（destinations）](#5-外部配信destinations)
6. [エラー時の挙動](#6-エラー時の挙動)
7. [主要ファイル対応](#7-主要ファイル対応)

---

## 1. エンドツーエンド俯瞰

```
┌─────────────────────────────────────────────────────────────────────┐
│  ユーザー操作                                                         │
│                                                                      │
│   A) CLI:  python -m cli.main <INPUT> -c <cassette> [--live] ...     │
│   B) Web:  streamlit run web/streamlit_app.py → ブラウザで操作       │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  カセットロード + モード決定                                           │
│                                                                      │
│   ① live:// URI or --live フラグ検知     │                           │
│   ② 旧カセット名 → canonical に自動置換   │  → load_cassette()        │
│   ③ apply_live_profile (live 時)         │     CassetteConfig 完成   │
│   ④ --override を順次適用                │                           │
│   ⑤ Pydantic validate (mode 整合性含む)   │                           │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  InputAdapter 選択                                                   │
│                                                                      │
│   cassette.input.type == "file"       → FileAdapter (local / drive)  │
│   cassette.input.type == "live_audio" → LiveAudioAdapter (BH/VB)     │
│   cassette.input.type == "zoom_sdk"   → ZoomSDKAdapter (skeleton)    │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Pipeline.run(input_uri, output_root, resume_run_id?)                │
│                                                                      │
│   adapter.acquire(uri) → local Path                                  │
│   run_id = YYYYMMDD_HHMMSS_<stem>                                    │
│   work_dir = output_root / run_id                                    │
│   Context 構築 (streaming flag 含む)                                  │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
  ┌──────── run_pre_hooks(ctx) ────────┐
  │                                     │
  │  check_ffmpeg                       │
  │  validate_input (拡張子 / 存在)     │
  │  validate_env (HF_TOKEN / API_KEY)  │
  └─────────────────┬─────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  _execute_steps (ctx)  [7 Step 直列]                                 │
│                                                                      │
│   for (step, runtime_name) in zip(steps, runtimes):                  │
│     if resume で完了済なら skip                                      │
│     on_step_start(name)                                              │
│     ctx = runtime.execute(step, ctx)                                 │
│     _save_checkpoint(ctx, step_name)                                 │
│     on_step_complete(name, elapsed)                                  │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
  ┌──────── log_summary(ctx) ──────────┐
  │                                     │
  │  Step 別 timing 表示                │
  │  aggregate_claude_usage で合算コスト│
  │  quality_check で品質警告           │
  └─────────────────┬─────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  _run_destinations(ctx)  [カセット output.destinations を順次]        │
│                                                                      │
│   local         → ctx.outputs のファイルを path にコピー              │
│   notion        → notion-client で DB にページ作成                   │
│   slack         → slack-sdk で投稿 or md アップロード                │
│   email         → smtplib (Gmail) で送信 (md 添付)                   │
│   google_drive  → service account で Drive にアップロード             │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
              adapter.cleanup() → 一時ファイル削除
                   │
                   ▼
              Context を返却（run_id, segments, outputs, meta）
```

---

## 2. 7 Step の内部（`Pipeline._execute_steps`）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  各 Step は Runtime (local or modal) 経由で実行                        │
│  Step.process(ctx) → ctx を mutate して返す                            │
└─────────────────────────────────────────────────────────────────────────┘

  入力  ctx.input_path              (例: meeting.mp4)
    │
    ▼
  [1/7] preprocess                  Provider: default | simple
    │     default: ffmpeg → noisereduce → librosa → 16kHz WAV
    │     simple:  ffmpeg + loudnorm (1-pass or 2-pass)
    │
    ├─ ctx.audio_path = {stem}_clean.wav
    └─ ctx.meta.preprocess = {sample_rate, duration_sec, loudnorm_mode, ...}
                             │
                             ▼
  [2/7] transcribe                  Provider: faster_whisper_batch |
    │                                          faster_whisper_chunked |
    │                                          whisper_streaming |
    │                                          whisper_cpp_coreml
    │     batch     : 全量 1 回、3 層ハルシネ防御
    │     chunked   : 20秒 chunk × overlap 2秒、merge_overlapping_segments
    │     streaming : LocalAgreement-N (N=2 既定) で 1〜3 秒遅延
    │     coreml    : pywhispercpp or whisper.cpp CLI (macOS)
    │
    │     cassette 名から initial_prompt 自動 fallback
    │     VAD リトライ（セグメント 0 or 総文字数 < 閾値）
    │     on_partial callback でチャンク毎に通知可能
    │
    ├─ ctx.segments = [{start, end, text, speaker="未割当"}, ...]
    └─ ctx.meta.transcribe = {provider, model, segment_count, ...}
                             │
                             ▼
  [3/7] diarize                     Provider: pyannote | channel_based
    │     pyannote       : Pipeline + use_whisperx_align（単語粒度境界）
    │                      失敗時は midpoint 割当にフォールバック
    │     channel_based  : 2ch 録音の Ch0/Ch1 を RMS 比で判定
    │                      (live_audio + mix=separate 向け)
    │
    ├─ ctx.segments[].speaker = 話者ラベル（または speaker_names で日本語）
    └─ ctx.meta.diarize = {align_mode, num_speakers_detected, distribution}
                             │
                             ▼
  [4/7] term_correct                Provider: regex
    │     vocab/terms/*.yaml を cassette.terms.stack の順に後勝ちでマージ
    │     各 segment.text に順次 re.subn で置換
    │
    ├─ ctx.segments[].text ← 補正済
    └─ ctx.meta.term_correct = {applied_count, stack, pattern_count}
                             │
                             ▼
  [5/7] llm_cleanup                 Provider: claude | none
    │     cloud_batch + batch_mode=true + chunks>=2 → Claude Batch API (50%割引)
    │     それ以外                                    → messages API 直通
    │     文末記号 > 無音 gap > 強制上限 の優先度で chunk 分割
    │     system_prompt_path (seminar 用も差替可) + glossary addendum
    │
    ├─ ctx.cleaned_text = 整形後テキスト
    └─ ctx.meta.llm_cleanup = {chunks, tokens_in/out, mode=batch|messages}
                             │
                             ▼
  [6/7] minutes_extract             Provider: claude
    │     system prompt = prompts/minutes_extract_{cassette}.md
    │     use_structured_output=true → tool_use で JSON 保証
    │                     false     → messages 応答 → _extract_json_block
    │                                  失敗時 1 回 retry（厳格指示追加）
    │
    ├─ ctx.minutes = {meeting_title, date, summary_3lines, ...}
    │                (カセット別スキーマ、sales / internal / seminar / 1on1 / interview)
    └─ ctx.meta.minutes_extract = {keys, tokens_in/out, mode=structured|text}
                             │
                             ▼
  [7/7] format                      Provider: default
    │     md  : Jinja2 (templates/{cassette}.md.j2) で minutes + segments 描画
    │     txt : `[秒.秒s] 話者: テキスト` 形式
    │     json: segments list をそのまま
    │     srt : 字幕（動画用）
    │
    └─ ctx.outputs = {"md": path, "json": path, "srt": path, "txt": path}
                             │
                             ▼
  出力  work_dir/                        ← run ごと
         ├── {stem}_clean.wav            ← preprocess
         ├── {stem}.md                   ← format
         ├── {stem}_data.json
         ├── {stem}.srt
         ├── chunks/                     ← chunked transcribe
         └── checkpoints/                ← resume 用
              ├── preprocess.json
              ├── transcribe.json
              └── ...
```

---

## 3. モード別の分岐（どこで何が変わるか）

### A. 録画ファイル（バッチ）
```
入力:    video.mp4 (file)
CLI:     python -m cli.main video.mp4 -c sales_meeting
Adapter: FileAdapter (storage=local | google_drive)
Profile: 素のカセット (preprocess=default, transcribe=batch, diarize=pyannote,
                       llm.batch_mode=true)
```

### B. ライブ録音（`--live` or `live://` URI）
```
入力:    "live://duration=60"
CLI:     python -m cli.main "live://duration=60" -c sales_meeting
Adapter: LiveAudioAdapter (BlackHole / VB-Cable 自動検出)
Profile: apply_live_profile() 適用後
         preprocess=simple, transcribe=chunked (large-v3-turbo),
         diarize=channel_based, llm.batch_mode=false
```

### C. 擬似リアルタイム字幕
```
入力:    live://... + --override transcribe.provider=whisper_streaming
Profile: ライブ + LocalAgreement-2
         on_partial でチャンクごとに commit された token 列を配信
Web UI:  Streamlit Live ページで逐次表示
```

### D. 再開（resume）
```
CLI:   python -m cli.main anything -c <cassette> --resume <run_id>
Flow:  _run_resume() → _find_run_dir → _load_latest_checkpoint →
       _restore_context (segments / cleaned_text / minutes 復元) →
       _execute_steps(skip_up_to=last_step)
```

### E. Streamlit Web UI
```
ブラウザ → web/streamlit_app.py
           Run / Live / History / Cassettes ページ
            ↓
          web/run_service.RunService.start_job()
            ↓ (threading.Thread)
          Pipeline.run() + on_step_start/complete → history.db
```

---

## 4. データ流（ctx 観点）

```
    input_path         audio_path           segments            cleaned_text         minutes              outputs
       │                  │                    │                    │                  │                    │
       │ preprocess       │                    │                    │                  │                    │
       ├────────────────>│                    │                    │                  │                    │
       │                  │ transcribe         │                    │                  │                    │
       │                  ├──────────────────>│                    │                  │                    │
       │                  │                    │ diarize            │                  │                    │
       │                  │                    ├──(speaker 付与)──>│                  │                    │
       │                  │                    │ term_correct       │                  │                    │
       │                  │                    ├──(text 補正)────>│                  │                    │
       │                  │                    │                    │ llm_cleanup      │                    │
       │                  │                    │                    ├────────────────>│                    │
       │                  │                    │                    │                  │ minutes_extract    │
       │                  │                    │                    │                  ├──────────────────>│
       │                  │                    │                    │                  │                    │ format
       │                  │                    │                    │                  │                    ├─(md/json/srt/txt)──> destinations
```

---

## 5. 外部配信（destinations）

```
  ctx.outputs (md/json/srt/txt)  +  ctx.minutes  +  ctx.cleaned_text
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
   LocalDestinationImpl   NotionDestinationImpl     SlackDestinationImpl
   ファイルコピー         notion-client でページ作成  summary_only: chat_postMessage
   (cassette.path)        properties Jinja2 レンダ    full_minutes: files_upload_v2

        ▼                        ▼
   EmailDestinationImpl   GoogleDriveDestinationImpl
   smtplib (Gmail)         service_account で upload
   subject Jinja2          drive-folder://<id>

   (失敗時: strict_destinations=true なら exit 1、既定は warning + 継続)
```

---

## 6. エラー時の挙動

| 位置 | 挙動 |
|---|---|
| pre_hooks 失敗（ffmpeg/env） | 即例外、pipeline 実行せず終了 |
| Step 実行中の例外 | `step.on_error(ctx, e)` で meta.errors 記録 → 再 raise → run() も例外 → checkpoint 途中まで残る → `--resume` で継続可 |
| destination 失敗（NotImplementedError 等） | warning + `ctx.meta.warnings` 追記 + 次の destination へ（strict=true 時は再 raise） |
| `on_partial` / `on_step_*` callback 失敗 | 捕捉して無視（メイン処理に影響させない） |
| adapter.cleanup 失敗 | warning のみ |

---

## 7. 主要ファイル対応

| 役割 | ファイル |
|---|---|
| CLI エントリ | `cli/main.py` |
| カセット読込・override・ライブプロファイル | `core/cassette.py` |
| Pipeline 本体 | `core/pipeline.py` |
| Context (dataclass) | `core/context.py` |
| Step ABC + レジストリ | `core/steps/base.py` |
| 7 Step 実装 | `core/steps/{preprocess,transcribe,diarize,term_correct,llm_cleanup,minutes_extract,format}.py` |
| InputAdapter | `core/adapters/{file,live_audio,zoom_sdk}.py` |
| Destinations | `core/destinations.py` |
| Runtime (local / modal) | `core/runtime.py` |
| Streaming (buffer / LA-N / captions) | `core/streaming/{buffer,local_agreement,pipeline,realtime_captions}.py` |
| Hooks (pre/post/cost) | `core/hooks.py` |
| LLM 共通 | `core/llm_client.py` |
| Web UI | `web/{streamlit_app,run_service,auth}.py` |
| ジョブ履歴 | `core/history.py` |

---

## 関連ドキュメント

- [USER_GUIDE.md](./USER_GUIDE.md) — 利用者向けの使い方（インストール〜運用）
- [PHASE0_DESIGN.md](./PHASE0_DESIGN.md) — プライバシーモード設計の根拠
- [ROADMAP.md](./ROADMAP.md) — Phase 0〜5 の実装ロードマップ
- [SETUP_LIVE_AUDIO_MACOS.md](./SETUP_LIVE_AUDIO_MACOS.md) / [WINDOWS](./SETUP_LIVE_AUDIO_WINDOWS.md) — ライブ音声セットアップ
- [SETUP_MODAL.md](./SETUP_MODAL.md) — Modal GPU 実行
- [SETUP_STREAMLIT.md](./SETUP_STREAMLIT.md) — Web UI 起動
