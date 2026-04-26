# Windows: Live Audio キャプチャ セットアップ手順

Phase 2 の `live_audio` 入力で **マイク + システム音声の 2ch キャプチャ**を行うための事前設定（Windows）。

## 全体像

```
┌──────────────┐
│ マイク       │──┐
└──────────────┘  │  ┌─────────────┐    ┌────────────┐
                  ├─►│ VoiceMeeter │───►│ CABLE      │───► meeting-hub
┌──────────────┐  │  │ (mixer)     │    │ Output     │    (2ch 録音)
│ アプリ音声   │──┘  └─────────────┘    └────────────┘
│ (Zoom/Meet)  │
└──────────────┘
```

**方式 A**: VoiceMeeter Banana + VB-Cable（推奨、2ch 分離が容易）
**方式 B**: VB-Cable のみ（mono ミックス、pyannote で話者分離）

## 方式 A: VoiceMeeter Banana（推奨）

### 1. インストール
1. [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) をダウンロード・管理者権限でインストール
2. [VoiceMeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) をダウンロード・管理者権限でインストール
3. 再起動

### 2. VoiceMeeter 設定
1. VoiceMeeter Banana を起動
2. **HARDWARE INPUT 1**: マイクを選択
3. **HARDWARE INPUT 2**: システム音声の録音元（WASAPI で「Stereo Mix」または仮想ケーブル）を選択
4. **HARDWARE OUT A1**: 実スピーカー or ヘッドフォンを選択
5. **B1** にルーティング: 両 INPUT を B1 にアサイン

### 3. Windows サウンド設定
1. コントロールパネル → サウンド
2. 既定の出力 → **VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)**
3. 既定の入力 → **VoiceMeeter Output B1 (VB-Audio VoiceMeeter VAIO)**
4. 会議アプリは既定デバイスを使用

### 4. meeting-hub から録音
```powershell
python -m cli.main "live://duration=60" -c one_on_one_live
```

- Ch1 = マイク（HARDWARE INPUT 1）
- Ch2 = システム音声（HARDWARE INPUT 2）

## 方式 B: VB-Cable のみ（mono ミックス）

1. VB-Cable インストール（上記 1. と同じ）
2. Windows サウンド → 出力 → **CABLE Input** を既定に
3. プロパティ → 聴く → 「このデバイスを聴く」で実スピーカーにも出力（聴くため）
4. meeting-hub のカセットは `mix: mono_merge` + `diarize: provider=pyannote`
5. マイクはシステム既定のまま（別 channel で同時録音できないため、**mono 合成になることに注意**）

**制約**: 方式 B では 2ch キャプチャができないため、`channel_based` 話者分離は使えない。pyannote 必須。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| VB-Cable が検出されない | 再起動、または管理者権限で再インストール |
| Ch2 が無音 | VoiceMeeter の HARDWARE INPUT 2 → B1 のルーティング確認 |
| エコーが発生 | VoiceMeeter の B1 を A1 にも流していないか（それでループが起きる）確認 |
| 録音が途切れる | VoiceMeeter の Buffer Size を大きめに（1024 / 2048） |

## 関連

- `docs/SETUP_LIVE_AUDIO_MACOS.md`（macOS 版）
- `core/adapters/live_audio.py`
- `cassettes/one_on_one_live.yaml`
