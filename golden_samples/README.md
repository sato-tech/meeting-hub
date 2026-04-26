# golden_samples/

Phase 1 回帰テストの基準データ。取得手順は `../REPORT_PROMPT_C.md` を参照。

このディレクトリには以下のみコミットする想定:
- `transcript.{txt,md}` / `data.json` / `subtitle.srt` / `metrics.json` / `log.txt`

**コミットしないもの（`.gitignore` で除外）**:
- `source.mp4` など原音声
- `*_clean.wav` など中間生成物

プライバシー機密が含まれる場合は、別途プライベートリポや暗号化保管を検討すること。
