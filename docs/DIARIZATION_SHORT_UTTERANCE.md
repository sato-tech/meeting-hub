# 話者分離 — 短発話・頻繁な話者切替への対応調査

> **生成日**: 2026-04-27
> **更新日**: 2026-04-27（P1〜P5 すべて実装済）
> **対象**: 現状（Phase 5 完了 + ライブプロファイル統合 + 精度改善 T1-T8 適用後）の meeting-hub
> **目的**: 「短い相槌や頻繁な話者切替に現実装が対応できているか」の検証 + 外部 OSS ツール比較
>
> **🟢 ステータス**: P1〜P5 すべて実装完了（259 tests pass）。詳細は §3 末尾のチェックリストを参照。

---

## 1. Executive Summary

1. 現実装には **8 箇所の構造的弱点**があり、特に「VAD 既定 300ms」「min_text_length=2」「midpoint 方式」「merge_gap=0.8s」の 4 つが短発話を取りこぼす主因。
2. 自前で直すなら **P1-P3（設定変更だけで完結）が即効性最大**で、半日〜1 日で WER（短発話）の体感が変わる。コード追加が要る P4-P5 は 1 週間目安。
3. 外部 OSS で乗り換える価値があるのは **NVIDIA NeMo（MSDD / Sortformer）** と **diart**（streaming）の 2 つ。前者は最高精度、後者はライブで遅延なし。
4. 1on1（2名固定）なら現 pyannote + 設定調整で十分。**3 名以上の相槌多発会議**で精度不足が顕在化するなら NeMo MSDD provider を新設するのが最短。
5. 既存運用での「短発話ミスの実害度」をユーザーが定量化できれば、投資判断は容易。最低限 P1-P3 を先に当てて、それで足りなければ外部ツール検討、の二段戦略を推奨。

---

## 2. 現状の弱点サマリ

### 2.1 VAD segment 粒度（min_silence_duration_ms=300ms）

**ファイル**: `core/steps/transcribe.py` L176-181, L264-266

```python
kwargs["vad_parameters"] = {
    "threshold": vad_threshold,                                                    # 既定 0.5
    "min_silence_duration_ms": int(self.params.get("vad_min_silence_ms", 300)),     # 既定 300ms
    "speech_pad_ms": int(self.params.get("vad_speech_pad_ms", 200)),                # 200ms
}
```

- **300ms 未満の無音は segment 区切りにならない** → 「うん 0.2s」のような相槌が前の発話に吸収される
- 全カセット YAML が既定値依存（明示 override なし）
- **影響度**: 大（短ターン会議の話者分離精度を直接損なう）

### 2.2 min_text_length=2 による 1 文字発話の除去

**ファイル**: `core/steps/transcribe.py` L286-293

```python
min_len = int(self.params.get("min_text_length", 2))
for seg in segments:
    text = seg["text"]
    if len(text) < min_len:
        continue  # 1 文字発話は完全除去
```

- 「ん」「あ」「ね」「は」のような 1 文字応答が transcribe 段階で消える
- diarize 以前の問題（segment が存在しないので話者割当も走らない）
- **影響度**: 大

### 2.3 pyannote midpoint 方式の限界

**ファイル**: `core/steps/diarize.py` L66-72（`_apply_to_segments`）

```python
mid = (float(seg["start"]) + float(seg["end"])) / 2
for turn, _track, spk in diarization.itertracks(yield_label=True):
    if turn.start <= mid <= turn.end:
        label = str(spk)
        break
```

- セグメント中央時刻の **1 点だけ**で話者判定
- 5 秒の segment 内で「A 話者 0-2.5s + B 話者 2.5-5s」の場合、どちらが取られるかは中央時刻の僅差で決まる
- whisperx align モード（L79-）で word 単位の割当はあるが、最終結果はセグメント粒度に丸められる
- **影響度**: 中（whisperx align が成功すれば軽減されるが、long segment の話者交代は依然として消える）

### 2.4 merge_gap_sec=0.8s が短ターン会話を潰す

**ファイル**: `core/streaming/local_agreement.py` L104-121（`tokens_to_segments`）

```python
def tokens_to_segments(tokens, *, merge_gap_sec: float = 0.8) -> list[dict]:
    ...
    if tok.start - current["end"] <= merge_gap_sec:
        current["end"] = tok.end
        current["text"] = f"{current['text']} {tok.text}".strip()
```

- whisper_streaming（LocalAgreement-N）出力で 0.8 秒以内の token は同一 segment に融合
- 「A: お疲れさまです」→ 0.5s pause →「B: お疲れさまです」が 1 segment になる
- channel_based diarize は 1 segment = 1 speaker 前提で動くため、誤割当
- **影響度**: 中（streaming 利用時のみ）

### 2.5 channel_based の RMS 閾値 0.6 が短相槌で揺らぐ

**ファイル**: `core/steps/diarize.py` L219-228

```python
threshold = float(self.params.get("dominant_threshold", 0.6))
...
ratio0 = ch0_rms / total
if ratio0 >= threshold:
    label = names[0]
elif ratio0 <= (1 - threshold):
    label = names[1]
else:
    label = names[0] if ch0_rms >= ch1_rms else names[1]  # 同時発話のフォールバック
```

- 0.3 秒以下の短相槌は窓内の無音割合が高く、RMS が不安定
- 両 ch に小音声が混じる（マイク漏れ等）と判定が揺れる
- 0.6 はやや厳しめ（自信を持てない segment が多くなる）
- **影響度**: 中（live_audio + mix=separate のみ）

### 2.6 segmentation_threshold / clustering_threshold が未配線

**ファイル**: `core/steps/diarize.py` L21-35（docstring）vs L126-135（実装）

```python
# docstring（L31-33）には記載あり
"""
  segmentation_threshold (float, default 0.4)
  clustering_threshold (float, default 0.65)
  min_cluster_size (int, default 15)
"""

# 実装は num_speakers / min_speakers / max_speakers のみを kwargs に入れる
kwargs: dict[str, Any] = {}
if num_speakers:
    kwargs["num_speakers"] = int(num_speakers)
else:
    kwargs["min_speakers"] = int(self.params.get("min_speakers", 2))
    kwargs["max_speakers"] = int(self.params.get("max_speakers", 4))
# ↑ segmentation_threshold 等は無視される
```

- カセット YAML（`sales_meeting.yaml` L49-50）には記載されているが、Pipeline に渡されていない
- pyannote の `instantiate()` 経由で本来は調整可能なパラメータ
- **影響度**: 中（pyannote のチューニング余地が活かせていない）

### 2.7 オーバーラップ発話を活用できていない

- pyannote 3.1 はオーバーラップ検出をサポートするが、`itertracks` で順次列挙する midpoint 方式では「最初にヒットした speaker」しか取れない
- 同時発話セグメントで実際に複数話者が同時に喋っているケースが捨てられる
- 商談での割り込み・社内 MTG での同時相槌が消える
- **影響度**: 中

### 2.8 短発話特化のテストケース不足

- `tests/unit/steps/test_diarize_mapping.py` のテストデータは 0.5〜2.0s
- `tests/unit/steps/test_channel_based_diarize.py` も 0.8〜0.9s
- **0.3 秒以下の相槌・連続短ターンを扱うテストがゼロ**
- 回帰検知が効かない領域

---

### 弱点まとめ表

| # | 弱点 | 影響度 | 対処コスト |
|---|---|---|---|
| 2.1 | VAD `min_silence_duration_ms=300` | 大 | カセット 1 行追加 |
| 2.2 | `min_text_length=2` で 1 文字除去 | 大 | カセット 1 行追加 |
| 2.3 | midpoint 方式 | 中 | コード追加（〜30行） |
| 2.4 | `merge_gap_sec=0.8` | 中 | カセット 1 行追加 |
| 2.5 | channel_based の閾値 0.6 | 中 | カセット 1 行調整 |
| 2.6 | pyannote params 未配線 | 中 | コード追加（5行） |
| 2.7 | overlap 未活用 | 中 | コード追加（〜50行） |
| 2.8 | テスト不足 | 小 | テスト追加（〜100行） |

---

## 3. 自前で直すなら（P1〜P5）

### P1（最優先・即効性）: VAD と min_text_length をカセット側で短発話向けに調整

**変更箇所**: `cassettes/*.yaml`（全 5 本）の `transcribe.params` に追加

```yaml
- step: transcribe
  provider: faster_whisper_batch
  params:
    vad_min_silence_ms: 100        # 300 → 100（相槌を独立 segment 化）
    vad_speech_pad_ms: 100          # 200 → 100（短発話の境界精度↑）
    min_text_length: 1              # 2 → 1（1 文字応答を残す）
```

- **工数**: 30 分（5 カセット × 数行）
- **期待効果**: 「はい」「うん」が segment として残る → diarize の対象に入る
- **リスク**: 短すぎるノイズも segment 化されるため、ハルシネーション件数が増える可能性。`hallucination_patterns` が既存で 7 パターン入っているので大半は救える
- **検証**: 既存ユーザーの実音声 1 サンプルで before/after 比較

### P2（短ターン streaming 用）: merge_gap_sec をカセット参照可能に

**変更箇所**: `core/steps/transcribe.py` の `WhisperStreamingStep.process` で `params.get("merge_gap_sec", 0.8)` を読む（既に対応済）+ ライブカセットで明示 override

```yaml
- step: transcribe
  provider: faster_whisper_chunked   # or whisper_streaming
  params:
    merge_gap_sec: 0.3   # 0.8 → 0.3
```

- **工数**: 30 分（params 露出確認 + カセット記述）
- **期待効果**: 0.3〜0.8 秒の連続短ターンが分離される
- **リスク**: 同一話者の短間隔発話まで分離してしまい、segment 数が増える
- **検証**: 既存テスト `test_local_agreement` 系で挙動確認

### P3（channel_based 微調整）: dominant_threshold を 0.55 に

**変更箇所**: `cassettes/one_on_one.yaml` 等で `--live` 時の override（または apply_live_profile の既定値）

```yaml
diarize:
  params:
    dominant_threshold: 0.55   # 0.6 → 0.55（短相槌で曖昧でも判定する）
```

- **工数**: 15 分
- **期待効果**: マイク漏れ込みで判定が揺れる短相槌でも、なんとか割当できる
- **リスク**: 同時発話セグメントで誤判定が増える可能性 → P1 と組み合わせて短 segment 化を先に行うことで緩和

### P4（コード追加・中工数）: pyannote params を配線

**変更箇所**: `core/steps/diarize.py` `PyannoteDiarizeStep.process`

```python
kwargs: dict[str, Any] = {}
if num_speakers:
    kwargs["num_speakers"] = int(num_speakers)
else:
    kwargs["min_speakers"] = int(self.params.get("min_speakers", 2))
    kwargs["max_speakers"] = int(self.params.get("max_speakers", 4))

# ── 追加 ──
for key in ("segmentation_threshold", "clustering_threshold", "min_duration_on", "min_duration_off"):
    if key in self.params:
        kwargs[key] = self.params[key]

diarization = pipeline(str(ctx.audio_path), **kwargs)
```

ただし pyannote 3.1 の API は `instantiate()` 経由が必要なケースもあるので、

```python
# 厳密には pyannote の HyperParameters を上書きする
pipeline.instantiate({
    "segmentation": {"threshold": self.params.get("segmentation_threshold", 0.4),
                     "min_duration_on": self.params.get("min_duration_on", 0.0),
                     "min_duration_off": self.params.get("min_duration_off", 0.0)},
    "clustering": {"method": "centroid",
                   "threshold": self.params.get("clustering_threshold", 0.7),
                   "min_cluster_size": self.params.get("min_cluster_size", 12)},
})
```

- **工数**: 2-3 時間（pyannote API 確認 + テスト追加）
- **期待効果**: `min_duration_on=0.0` で短発話を逃さなくなる、`segmentation_threshold` を下げると検出感度↑
- **リスク**: pyannote のバージョンによって API が違う。3.1 と 3.2 で kwargs が変わる
- **検証**: pyannote 3.1 を実機で動かしてパラメータ反映を確認

### P5（コード追加・word 単位 speaker 保持）: WhisperX align モードを真に活用

**変更箇所**: `core/steps/diarize.py` `_apply_with_whisperx_align`

```python
# 現状: result["segments"] からセグメント単位 speaker を取り出して終了
# 改善: result["segments"][i]["words"] の word 単位 speaker を確認し、
#       segment 内で speaker が変わっていたら **segment を分割** する

for orig, r in zip(segments, result_segments):
    words = r.get("words") or []
    if len(words) > 1:
        # word ごとの speaker をチェック
        speakers_in_segment = {w.get("speaker") for w in words if w.get("speaker")}
        if len(speakers_in_segment) > 1:
            # speaker 変化点で分割
            sub_segments = _split_by_speaker_change(orig, words)
            labeled.extend(sub_segments)
            continue
    label = str(r.get("speaker") or "UNKNOWN")
    out = dict(orig)
    out["speaker"] = speaker_names.get(label, label)
    labeled.append(out)
```

- **工数**: 4-6 時間（実装 + テスト）
- **期待効果**: 長 segment 内の話者交代を検出可能
- **リスク**: segment 数が大幅に増えると下流（llm_cleanup の chunk 構築）に影響
- **検証**: 短ターン会議の golden_sample で前後比較

### P1-P5 まとめ

| # | 案 | 工数 | 効果 | コード変更 | ステータス |
|---|---|---|---|---|---|
| **P1** | カセットに VAD・min_text_length 追加 | 30 分 | ★★★ | なし | ✅ **実装済** |
| **P2** | merge_gap_sec をライブで 0.3 に | 30 分 | ★★ | なし | ✅ **実装済** |
| **P3** | dominant_threshold を 0.55 に | 15 分 | ★ | なし | ✅ **実装済** |
| **P4** | pyannote params 配線 | 2-3 時間 | ★★ | あり | ✅ **実装済** |
| **P5** | word 単位 speaker で segment 分割 | 4-6 時間 | ★★★ | あり | ✅ **実装済** |

### 実装内容（2026-04-27 完了）

- **P1**: 全 5 カセット（sales/internal/seminar/one_on_one/interview）の `transcribe.params` に
  `vad_min_silence_ms: 100` / `vad_speech_pad_ms: 100` / `min_text_length: 1` を追加
- **P2**: `core/cassette.py:apply_live_profile()` で transcribe params に
  `merge_gap_sec: 0.3` を setdefault（ライブモード時のみ有効）
- **P3**: 同 `apply_live_profile()` の channel_based diarize で `dominant_threshold: 0.55`
- **P4**: `core/steps/diarize.py:PyannoteDiarizeStep._instantiate_hyperparams()` 新規追加
  - `segmentation_threshold` / `min_duration_on` / `min_duration_off`
  - `clustering_threshold` / `clustering_method` / `min_cluster_size`
  - いずれもカセット params に明示があるときだけ `pipeline.instantiate()` で反映
- **P5**: `_apply_with_whisperx_align` 拡張 + `_split_segment_by_word_speakers` 新規
  - 1 segment 内で word の speaker が変わる場合、speaker 連続区間で分割
  - speaker 不明 word は直前の speaker を継承
  - word の start/end が無い場合は orig 区間を均等分割（フォールバック）
  - `params.split_on_speaker_change=false` で従来挙動に戻せる

**追加テスト**: `tests/unit/steps/test_diarize_short_utterance.py`（12 件）

CLI 確認:
```
$ python -m cli.main meeting.mp4 -c sales_meeting --dry-run
  ✓ transcribe (...): vad_min_silence_ms=100, vad_speech_pad_ms=100, min_text_length=1

$ python -m cli.main "live://duration=60" -c one_on_one --dry-run
  ✓ transcribe (...): merge_gap_sec=0.3, vad_min_silence_ms=100, ...
  ✓ diarize (channel_based): dominant_threshold=0.55, ...
```

---

## 4. 外部ツール比較

短発話・話者切替頻繁・overlap に強いとされる主要 OSS / 商用ライブラリを 8 つ整理。

### 4.1 NVIDIA NeMo MSDD（Multi-scale Diarization Decoder）

**仕組み**: 0.5s / 1.0s / 1.5s の **複数スケール**で embedding を取得し、attention で統合してフレーム単位に speaker を割当。短発話・overlap に強い。

| 項目 | 値 |
|---|---|
| ライセンス | Apache-2.0 |
| 短発話精度 | ★★★（業界トップクラス） |
| Overlap 対応 | ◯（ネイティブ） |
| 日本語対応 | ◯（言語非依存の embedding） |
| GPU 必須 | 推奨（CPU でも動くが遅い） |
| 統合難易度 | 中（NeMo SDK 全体を入れる必要あり） |
| 実装工数 | 2〜3 日（provider 新設 + Modal 連携） |
| 採用判定済み？ | meeting-hub の `core/evaluation.py` に `_run_nemo()` skeleton あり、本実装は利用者待ち |

```
推奨用途: 3 名以上 + 相槌多発の社内 MTG / セミナー Q&A
```

### 4.2 diart（pyannote ベースの online streaming diarization）

**仕組み**: pyannote の segmentation / embedding モデルを使うが、**インクリメンタルにクラスタリング**する。録音終了を待たずにライブで話者ラベルを返せる。

| 項目 | 値 |
|---|---|
| ライセンス | MIT |
| 短発話精度 | ★★（pyannote 同等、streaming 構造で多少劣化） |
| Overlap 対応 | ◯（pyannote 由来） |
| 日本語対応 | ◯ |
| GPU 必須 | 不要（CPU でも実用） |
| 統合難易度 | 低（pyannote 既存環境ほぼそのまま） |
| 実装工数 | 1 日（provider 新設） |
| 公式 | https://github.com/juanmc2005/diart |

```
推奨用途: ライブ字幕（whisper_streaming + diart の組合せで真の real-time 話者分離）
```

### 4.3 pyannote + 3D-Speaker（Alibaba / WeSpeaker）

**仕組み**: pyannote の segmentation + clustering で話者境界を取り、embedding 抽出を **3D-Speaker（CAM++ 等の高精度モデル）** に置き換える。短発話の embedding 品質が向上。

| 項目 | 値 |
|---|---|
| ライセンス | Apache-2.0（3D-Speaker） |
| 短発話精度 | ★★（embedding 段階のみ強化） |
| Overlap 対応 | ◯（pyannote の segmentation を使うため） |
| 日本語対応 | ◯ |
| GPU 必須 | 不要 |
| 統合難易度 | 中（embedding model だけ差し替え） |
| 実装工数 | 1〜2 日 |
| 公式 | https://github.com/modelscope/3D-Speaker |

```
推奨用途: 既存 pyannote 環境を活かしつつ embedding だけ強化したいケース
```

### 4.4 WhisperX 内蔵 diarize の word 単位活用（自前 P5 と同じ方向）

**仕組み**: WhisperX は内部で `whisperx.diarize` パイプラインを持つ。これは pyannote ベースだが、**word_timestamps + alignment** を強く前提にしているため、word 単位で speaker を返す。

- 現実装は `assign_word_speakers` を呼んでいるがセグメント粒度で丸めている
- WhisperX のフルパイプライン（`load_diarize_model` → `assign_word_speakers`）に乗せ替えれば、word-level speaker を活かせる

| 項目 | 値 |
|---|---|
| ライセンス | BSD（WhisperX）+ MIT（pyannote） |
| 短発話精度 | ★★（pyannote と同等、word align で境界精度↑） |
| Overlap 対応 | △（pyannote 経由） |
| 日本語対応 | ◯ |
| GPU 必須 | 推奨（align モデルが GPU 前提） |
| 統合難易度 | 低（依存は既にあり） |
| 実装工数 | 半日〜1 日（既存 `_apply_with_whisperx_align` を拡張） |

```
推奨用途: 既存依存の中で短発話精度を底上げしたい（自前 P5 と実質同じ）
```

### 4.5 Resemblyzer + spectral clustering

**仕組み**: 軽量な GE2E embedding（256d）で 0.5 秒程度の窓ごとに特徴抽出 → spectral clustering で話者推定。**最もシンプル**で、依存も少ない。

| 項目 | 値 |
|---|---|
| ライセンス | Apache-2.0 |
| 短発話精度 | ★（embedding 品質は pyannote より低い） |
| Overlap 対応 | ✗ |
| 日本語対応 | ◯ |
| GPU 必須 | 不要 |
| 統合難易度 | 低 |
| 実装工数 | 半日（プロトタイプ） |
| 公式 | https://github.com/resemble-ai/Resemblyzer |

```
推奨用途: pyannote が動かない環境のフォールバック、軽量プロトタイプ
```

### 4.6 Reverb（Rev.com 公開、2024）

**仕組み**: Rev.com（商用文字起こし）の **OSS 化されたモデル**。WhisperX + 独自 diarization。短発話・低品質音声に強い。

| 項目 | 値 |
|---|---|
| ライセンス | Apache-2.0 |
| 短発話精度 | ★★★（商用品質） |
| Overlap 対応 | ◯ |
| 日本語対応 | △（英語特化、日本語は要検証） |
| GPU 必須 | 推奨 |
| 統合難易度 | 中（Reverb 全体を取り込み） |
| 実装工数 | 2-3 日 |
| 公式 | https://github.com/revdotcom/reverb |

```
推奨用途: 英語会議が中心の現場（meeting-hub の主用途は日本語なので優先度低）
```

### 4.7 DiariZen / EEND-VC（End-to-End Neural Diarization with Vector Clustering）

**仕組み**: フレーム単位の **End-to-End** で話者分離を行うニューラルモデル。多人数 + overlap で従来法より大幅に精度↑。CHiME-7 / DIHARD で SOTA。

| 項目 | 値 |
|---|---|
| ライセンス | MIT |
| 短発話精度 | ★★★ |
| Overlap 対応 | ◯（ネイティブ、複数話者同時出力） |
| 日本語対応 | ◯ |
| GPU 必須 | 必須 |
| 統合難易度 | 高（モデル DL + 推論パイプライン構築） |
| 実装工数 | 3-5 日 |
| 公式 | https://github.com/BUTSpeechFIT/DiariZen |

```
推奨用途: 5名以上の社内 MTG / パネルディスカッション形式のセミナー
```

### 4.8 SpeechBrain ECAPA-TDNN + Spectral Clustering

**仕組み**: SpeechBrain の ECAPA-TDNN（話者検証モデル）で embedding 抽出 + spectral clustering。**短発話 embedding が良好**（ECAPA は 0.5s でも安定）。

| 項目 | 値 |
|---|---|
| ライセンス | Apache-2.0 |
| 短発話精度 | ★★ |
| Overlap 対応 | ✗ |
| 日本語対応 | ◯ |
| GPU 必須 | 不要 |
| 統合難易度 | 中 |
| 実装工数 | 1-2 日 |
| 公式 | https://github.com/speechbrain/speechbrain |

```
推奨用途: pyannote の segmentation は良いが embedding を強化したい中庸ケース
```

### 比較表（要約）

| ツール | 短発話 | Overlap | 日本語 | GPU | 工数 | 用途別の最適 |
|---|:---:|:---:|:---:|:---:|---|---|
| **NeMo MSDD** | ★★★ | ◯ | ◯ | 推奨 | 2-3 日 | 多人数 MTG、最高精度 |
| **diart** | ★★ | ◯ | ◯ | 不要 | 1 日 | ライブ字幕 |
| **pyannote+3D-Speaker** | ★★ | ◯ | ◯ | 不要 | 1-2 日 | 既存環境の延長 |
| **WhisperX word-level** | ★★ | △ | ◯ | 推奨 | 半日 | 既存依存活用 |
| **Resemblyzer** | ★ | ✗ | ◯ | 不要 | 半日 | プロトタイプ |
| **Reverb** | ★★★ | ◯ | △ | 推奨 | 2-3 日 | 英語会議 |
| **DiariZen** | ★★★ | ◯ | ◯ | 必須 | 3-5 日 | 多人数 + overlap 多発 |
| **SpeechBrain** | ★★ | ✗ | ◯ | 不要 | 1-2 日 | embedding 強化のみ |
| **現状 pyannote 3.1** | ★ | △ | ◯ | 不要 | 0 | （ベースライン） |

> ※ 短発話★は < 0.5s ターンの recall/precision を 5 段階で主観評価（業界の通説 + 公開ベンチを総合）。実機ベンチは別途必要。

---

## 5. 用途別の推奨マッピング

| ユースケース | 推奨アプローチ | 根拠 |
|---|---|---|
| **1on1（2 名固定）** | 現 pyannote + P1+P3（カセット調整のみ） | 2 名は誤りにくい、相槌対応だけ強化すれば十分 |
| **商談（2-4 名、相槌多発）** | P1+P2+P3 → 不足なら NeMo MSDD provider 新設 | まず設定で底上げ、それで足りなければ最高精度へ |
| **社内 MTG（3-6 名、割込多発）** | NeMo MSDD（overlap 検出 + multi-scale） | pyannote の限界を超える領域 |
| **セミナー（1 名 + 質問数名）** | 既存（diarize=enabled: false で十分） | 話者分離の優先度低い |
| **採用面談（2-4 名）** | P1+P3 + word-level 活用（P5） | プライバシー上 NeMo を回避、ローカル維持 |
| **ライブ字幕（1on1 含む）** | diart + whisper_streaming | streaming に最適化された組合せ |

---

## 6. 段階的な導入ロードマップ

### Stage 1: 即効性（半日〜1 日）
- **P1**: 全カセットに `vad_min_silence_ms: 100`, `vad_speech_pad_ms: 100`, `min_text_length: 1` を追加
- **P2**: `live_*` カセット（実質 `apply_live_profile`）で `merge_gap_sec: 0.3` を既定化
- **P3**: `apply_live_profile` の channel_based 既定で `dominant_threshold: 0.55`
- **テスト**: 短発話特化のフィクスチャを 1 本追加（0.3s 相槌 × 5 回の合成音声）

→ **既存 pyannote のままで体感 30-50% 改善** が見込める

### Stage 2: 中期（3〜7 日）
- **P4**: pyannote `instantiate()` で segmentation_threshold / min_duration_on を配線
- **P5**: WhisperX word-level speaker で segment 分割（既存 `_apply_with_whisperx_align` 拡張）
- **テスト**: golden_samples に短ターン会議サンプルを 1 本追加

→ **pyannote の機能を最大化**、これでも不足なら Stage 3 へ

### Stage 3: 長期（2-4 週間、選択的）
- **NeMo MSDD provider 新設** または **diart streaming provider 新設**
- カセットで `diarize.provider=nemo` / `diarize.provider=diart` を選択可能に
- Modal Labs に NeMo deploy（GPU、Phase 3 の Modal infra 流用）
- 既存 `core/evaluation.py` の `_run_nemo()` を本実装

→ **業界 SOTA 級の精度**、用途次第で投資判断

---

## 7. 評価方法

短発話精度を継続的に確認するため、以下を整備すると良い:

### 7.1 短発話特化テストフィクスチャ

`tests/fixtures/audio/` に以下を追加:

| ファイル | 内容 | 期待 |
|---|---|---|
| `short_aizuchi_2speakers.wav` | A 「で、これが提案で」→ B 「はい」（0.2s） → A 「もう一つあって」 | 「はい」が独立 segment、speaker=B |
| `rapid_turn_2speakers.wav` | A 「うん」B 「はい」A 「OK」を 1.5 秒間隔で 10 回 | 10 segments、A/B が交互 |
| `overlap_3speakers.wav` | A・B 同時発話 1 秒 + C 単独 1 秒 | overlap で AB 両方検出（理想） |
| `whisper_speech_2speakers.wav` | A 通常音量 + B ささやき声 | 両方 segment 化される |

### 7.2 短発話特化メトリクス

`core/evaluation.py` に追加:

```python
def short_utterance_metrics(
    hypothesis: list[dict],
    reference: list[dict],
    *,
    short_threshold_sec: float = 0.5,
) -> dict[str, float]:
    """0.5 秒未満の発話に絞った recall / precision / F1。"""
    short_ref = [s for s in reference if s["end"] - s["start"] < short_threshold_sec]
    short_hyp = [s for s in hypothesis if s["end"] - s["start"] < short_threshold_sec]
    # IoU マッチングで TP/FP/FN を計算
    ...
```

### 7.3 golden_samples に短ターン会議追加

`golden_samples/S04/01/` に「相槌多めの 1on1」5 分を 1 本追加し、metrics.json で短発話 F1 をベースライン記録。Phase 1 の回帰テスト枠組みに乗せる。

---

## 8. 未解決の確認事項

ユーザー判断を希望する項目:

1. **実害の定量化**: 既存運用で「短発話の取りこぼし」がどの程度の頻度・どの程度の品質劣化として顕在化しているか。月 N 件中 M 件で発生、等の数字があれば投資判断が容易。
2. **採用判断の優先軸**: 精度（最大化したい）/ 速度（live で 1 秒以内）/ コスト（GPU 月額）/ 実装工数（人日）のどれを最優先にするか。
3. **NeMo / diart 採用是非**: Phase 4 で「NeMo 評価結果に基づき切替判断」が ROADMAP にあったが、未実施。本調査を機にユーザー実機で評価するか、それとも当面 P1-P3 で凌ぐか。
4. **短発話テスト基準音源の入手**: `tests/fixtures/audio/short_*` を合成音声（gTTS / VOICEVOX）で作るか、実音声を録音するか。
5. **評価指標の追加**: DER に加えて短発話特化 F1 を導入するか。

---

## 関連ドキュメント

- [docs/USER_GUIDE.md](./USER_GUIDE.md) §12 トラブルシューティング「話者分離の精度が低い」
- [docs/PHASE0_DESIGN.md](./PHASE0_DESIGN.md) §4 技術スタック（pyannote 3.1 / NeMo 評価予定）
- [docs/PHASE4_COMPLETION.md](./PHASE4_COMPLETION.md) §3.3 NeMo 評価フレームワーク
- [docs/FLOW.md](./FLOW.md) §2 7 Step の内部 — diarize Step の入出力
- `core/steps/diarize.py` — 現実装
- `core/evaluation.py` — DER 計算と `_run_nemo()` skeleton

---

## 参考文献（公開資料）

- pyannote.audio 3.1: https://huggingface.co/pyannote/speaker-diarization-3.1
- NVIDIA NeMo MSDD: https://docs.nvidia.com/deeplearning/nemo/user-guide/docs/en/main/asr/speaker_diarization/models.html
- diart: https://github.com/juanmc2005/diart
- WhisperX: https://github.com/m-bain/whisperX
- 3D-Speaker: https://github.com/modelscope/3D-Speaker
- Reverb: https://github.com/revdotcom/reverb
- DiariZen: https://github.com/BUTSpeechFIT/DiariZen
- Macháček et al. 2023 "Turning Whisper into Real-Time Transcription System": https://arxiv.org/abs/2307.14743
