# Notion DB スキーマ定義

> 5カセット分の Notion DB 構造定義。Phase 2 完了時点までに Notion 側で
> これらの DB を事前構築しておく必要があります。

---

## 前提: 環境変数

各 DB の ID を `.env` に登録:

```bash
NOTION_DB_SALES=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
NOTION_DB_INTERNAL=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
NOTION_DB_SEMINAR=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
NOTION_DB_RECRUITING=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# one_on_one は Notion 連携なし（プライバシー重視）
```

---

## 1. 商談DB（`NOTION_DB_SALES`）

用途: 商談議事録の横断検索・進捗管理

| プロパティ名 | タイプ | 必須 | 備考 |
|---|---|---|---|
| Title | Title | ◯ | 議事録タイトル（例: "{{ company }} 初回商談"） |
| Date | Date | ◯ | 商談日 |
| Company | Text | ◯ | 顧客企業名 |
| Stage | Select | ◯ | 初回 / 2回目 / 提案 / クロージング / その他 |
| Participants | Multi-select | | 参加者（自社+顧客） |
| Summary | Text | ◯ | 3行サマリ |
| NextActions | Text | | 次アクション（箇条書き） |
| AudioURL | URL | | Google Drive の音声ファイル URL |
| Budget | Text | | 予算感 |
| Competitors | Multi-select | | 競合 |
| Status | Select | | フォロー中 / 受注 / 失注 / 保留 |

### Select オプション推奨値
- Stage: `初回`, `2回目`, `提案`, `クロージング`, `その他`
- Status: `フォロー中`, `受注`, `失注`, `保留`

---

## 2. 社内MTG DB（`NOTION_DB_INTERNAL`）

用途: 社内会議議事録の一元管理

| プロパティ名 | タイプ | 必須 | 備考 |
|---|---|---|---|
| Title | Title | ◯ | MTG タイトル |
| Date | Date | ◯ | 開催日 |
| MeetingType | Select | ◯ | 定例 / プロジェクト / 意思決定 / ブレスト / その他 |
| Participants | Multi-select | | 参加者 |
| Summary | Text | ◯ | 会議要約 |
| Decisions | Text | | 決定事項（箇条書き） |
| ToDos | Text | | ToDo リスト |
| OpenIssues | Text | | 継続検討論点 |
| Department | Select | | 部署 |

### Select オプション推奨値
- MeetingType: `定例`, `プロジェクト`, `意思決定`, `ブレスト`, `その他`
- Department: 実際の部署構成に合わせて設定

---

## 3. セミナー DB（`NOTION_DB_SEMINAR`）

用途: セミナー講演アーカイブ

| プロパティ名 | タイプ | 必須 | 備考 |
|---|---|---|---|
| Title | Title | ◯ | セミナータイトル |
| Date | Date | ◯ | 開催日 |
| Speakers | Multi-select | | 登壇者 |
| Duration | Text | | 所要時間（例: "90分"） |
| Summary | Text | ◯ | 3行概要 |
| Chapters | Text | | 章立てタイトル（箇条書き） |
| FullTextURL | URL | | 全文Markdownファイルの URL |
| Tags | Multi-select | | テーマタグ（例: AI, 営業, マーケティング） |

---

## 4. 採用DB（`NOTION_DB_RECRUITING`）

用途: 候補者評価の一元管理

⚠️ **アクセス権限を限定**: 採用担当者のみが閲覧可能に設定すること

| プロパティ名 | タイプ | 必須 | 備考 |
|---|---|---|---|
| Candidate | Title | ◯ | 候補者名 |
| Position | Select | ◯ | 募集ポジション |
| Date | Date | ◯ | 面談日 |
| Interviewers | Multi-select | | 面接官 |
| TechnicalScore | Number | | 1〜5 |
| CultureFitScore | Number | | 1〜5 |
| CommunicationScore | Number | | 1〜5 |
| ProblemSolvingScore | Number | | 1〜5 |
| GrowthMotivationScore | Number | | 1〜5 |
| TotalScore | Formula | | 5項目平均（自動計算） |
| Recommendation | Select | ◯ | 強く推薦 / 推薦 / 保留 / 不採用 |
| Summary | Text | ◯ | 面談要約 |
| Stage | Select | | 一次面接 / 二次面接 / 最終面接 / 内定 / 辞退 |

### Select オプション推奨値
- Position: 実際の募集ポジションに合わせて設定
- Recommendation: `強く推薦`, `推薦`, `保留`, `不採用`
- Stage: `一次面接`, `二次面接`, `最終面接`, `内定`, `辞退`

### Formula 例（TotalScore）
```
round((prop("TechnicalScore") + prop("CultureFitScore") + prop("CommunicationScore") + prop("ProblemSolvingScore") + prop("GrowthMotivationScore")) / 5 * 10) / 10
```

---

## 5. 1on1 DB（作成しない）

**意図的に Notion DB を用意しない**。1on1 は心理的安全性が最重要のため、
ローカル保存のみとし、本人以外がアクセスできないようにする。

議事録は各自のローカルディスクに `./output/one_on_one/` で保存され、
共有が必要な場合は本人が手動で共有する。

---

## 運用ルール

### アクセス権限
- 商談 / 社内MTG / セミナーDB: チーム全員が閲覧可能
- 採用DB: 採用担当者のみ閲覧可能（権限付与は Notion 側で管理）
- 1on1: DB 作成しない

### データ削除ポリシー
- 「制限なし、手動削除」の方針に従う
- 契約終了・退職時等の削除は管理者が手動で対応
- Notion の「ゴミ箱」を有効化し、誤削除を防ぐ

### 監査ログ
- Notion 側の「更新履歴」を活用
- 統合リポ側では Notion 投稿を `history.db`（SQLite）にも記録
