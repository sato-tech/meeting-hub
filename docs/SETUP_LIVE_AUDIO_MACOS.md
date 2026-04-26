# macOS: Live Audio キャプチャ セットアップ手順

Phase 2 の `live_audio` 入力で **マイク + システム音声の 2ch キャプチャ**を行うための事前設定。

## 全体像

```
┌──────────────┐    ┌──────────────────────┐    ┌────────────┐
│ マイク       │───►│ Aggregate Device     │───►│ Whisper    │
│              │    │ (Ch1=Mic, Ch2=Sys)   │    │ + meeting- │
└──────────────┘    └──────────────────────┘    │   hub      │
┌──────────────┐    ┌──────────────────────┐    └────────────┘
│ アプリ音声   │───►│ Multi-Output Device  │
│ (Zoom/Meet)  │    │ ┌─ 実スピーカー      │
└──────────────┘    │ └─ BlackHole 2ch     │
                    └──────────────────────┘
```

- `Multi-Output Device`: アプリ音声を **実スピーカー** と **BlackHole** に同時出力
- `Aggregate Device`: マイクと BlackHole を 1 デバイスに合成し、Ch1/Ch2 として同時入力
- `meeting-hub` はこの Aggregate Device を入力デバイスとして 2ch 録音

## 1. BlackHole 2ch インストール

```bash
brew install --cask blackhole-2ch
```

インストール後、システム再起動（または `killall coreaudiod` で足りる場合あり）。

## 2. Multi-Output Device の作成

1. `Audio MIDI Setup.app`（スポットライトで「Audio MIDI」）を開く
2. 左下 `+` → **「Multi-Output Device を作成」**
3. 作成されたデバイスのチェックボックスで:
   - ✅ 内蔵スピーカー or ヘッドフォン（実際に聴くデバイス）
   - ✅ BlackHole 2ch
4. 右側で **マスタークロックを「内蔵」**に、**ドリフト補正を BlackHole 側で ON** 推奨
5. 名前を `Meeting Output`（任意）に変更

## 3. Aggregate Device の作成

1. 同じ `Audio MIDI Setup.app` で `+` → **「機器セットを作成」**
2. チェック:
   - ✅ BlackHole 2ch（システム音声）
   - ✅ MacBook Pro のマイク（または外部マイク）
3. 名前を `Meeting Input`（任意）に変更

## 4. システム設定で出力を切替

1. システム設定 → サウンド → 出力
2. **Meeting Output** を選択
3. 会議アプリ（Zoom / Google Meet）を起動すると、音声が実スピーカーと BlackHole の両方に流れる

## 5. meeting-hub から録音

```bash
# デバイス確認（任意）
python -c "import sounddevice as sd; print(sd.query_devices())"

# デフォルト（60秒録音）
python -m cli.main "live://duration=60" -c one_on_one_live

# 時間指定（5分）
python -m cli.main "live://duration=300" -c one_on_one_live
```

## 会議終了後のチェック

- 生成された WAV は 2ch（Ch1=マイク / Ch2=システム音声）
- 話者分離 provider に `channel_based` を指定すれば pyannote 不要で話者を割当できる（`one_on_one_live.yaml` の既定）

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| BlackHole が検出されない | システム設定 → プライバシーとセキュリティ → マイク で Terminal/iTerm に許可 |
| Ch2 が無音 | 出力を Multi-Output Device に切り替え忘れていないか確認 |
| 音量が小さい | `preprocess.params.loudnorm` を指定、または Aggregate の音量を調整 |
| 録音が片 ch のみ | `mix: separate` になっているか確認、`Audio MIDI Setup` のドリフト補正を有効化 |

## 関連

- `REPORT_PHASE2_PLAN.md §3`
- `core/adapters/live_audio.py`
- `cassettes/one_on_one_live.yaml`
