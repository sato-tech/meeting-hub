# Zoom Meeting SDK 対応（**保留中**）

> **ステータス**: Phase 5 時点で **skeleton のみ**。実装再開は下記「復活条件」を全て満たした後。
> **代替策**: macOS BlackHole / Windows VB-Cable 経由の `LiveAudioAdapter` で Zoom 会議音声は問題なく取得可能（`docs/SETUP_LIVE_AUDIO_*.md`）。

---

## なぜ保留なのか

1. **Zoom Marketplace 開発者登録** は社内承認を要する（営業・情報システム部門との調整）
2. **Zoom 有料プラン** が Meeting SDK 利用条件を満たすか未検証
3. **Python バインディング**の OSS 状況が十分でない（公式 C++/Electron SDK 中心、Python は非公式ラッパ）
4. Phase 2 で導入した `LiveAudioAdapter` が既に Zoom 音声を十分な品質で取得できており、**導入コストに見合うメリットが不明確**

---

## 復活条件（これらが全部揃ったら本実装に着手）

- [ ] Zoom Marketplace 開発者アカウントの **社内承認取得**（営業/情シス）
- [ ] 利用中の Zoom プランが **Meeting SDK** をサポートしていることの確認（Business / Enterprise / Education）
- [ ] SDK Key / SDK Secret の発行とセキュア保管（`secrets/` 配下 or Vault）
- [ ] **Python バインディングの選定**（以下のいずれか）
  - 公式 C++ SDK を `pybind11` で自作ラップ
  - 既存 OSS ラッパ（`zoomsdk-py` 等）の品質・メンテ状況確認
  - WebSocket/Electron 経由でのプロキシ実装
- [ ] **精度比較**: `LiveAudioAdapter`（Multi-Output Device 経由）と ZoomSDK Raw Data の WER を実測
- [ ] **工数見積**: 初期実装・テスト・メンテ込みで工数 vs 得られる価値の最終判断

---

## 実装時の設計メモ（再開時のためのヒント）

### ファイル構成
```
core/adapters/zoom_sdk.py          ← ZoomSDKAdapter 本実装
scripts/zoom_sdk_jwt_signer.py     ← SDK JWT 生成のユーティリティ
docs/SETUP_ZOOM_SDK.md             ← この文書、実装完了時に "本実装" に更新
```

### 依存（案）
```
# requirements に追加予定
pyjwt>=2.8                  # SDK JWT 生成
zoomsdk-py>=0.x             # 選定結果による
```

### env
```
ZOOM_SDK_KEY=xxxxxxxxxxxx
ZOOM_SDK_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ZOOM_MEETING_ID=<meeting id>
ZOOM_MEETING_PASSWORD=<password>  # optional
```

### カセット例（復活時）
```yaml
input:
  type: zoom_sdk
  source_preference: [zoom_sdk, system_audio]   # zoom が失敗したら system_audio にフォールバック
```

### CLI
```bash
python -m cli.main "zoom://<meetingId>" -c live_sales
```

### Step 連携
- ZoomSDK Raw Data は **16kHz mono PCM** が得られる（公式仕様）
- `preprocess` は不要（既に 16kHz）、`provider=simple` でパススルー
- `transcribe.provider=whisper_streaming` で 1〜3 秒遅延のライブ字幕
- 話者分離は Zoom SDK の `user_id` を使って **channel_based** provider の変種を作るのが筋

---

## 運用上の制約（実装後に書き換える欄）

- （実装後に実測値を記載）
- （実装後に制約を記載）

---

## 現在の運用推奨

**ZoomSDK を待たず、以下で十分に運用可能**:

- macOS: `brew install --cask blackhole-2ch` + Multi-Output Device（`docs/SETUP_LIVE_AUDIO_MACOS.md`）
- Windows: VoiceMeeter Banana + VB-Cable（`docs/SETUP_LIVE_AUDIO_WINDOWS.md`）
- カセット: `live_sales` / `live_internal` / `one_on_one_live`
- リアルタイム化: `transcribe.provider=whisper_streaming`（Phase 5 で本実装済）
