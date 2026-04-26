"""
cassette_schema.py — カセット（会議種別プロファイル）の Pydantic スキーマ定義

このファイルは Phase 0 の設計成果物であり、YAML カセットをロード・検証するための
正式なスキーマである。実装時はこの定義を core/cassette.py 等に配置し、
cassettes/*.yaml をこのスキーマで検証する。

設計原則:
  - プライバシーモード（local / local_llm / cloud_batch / cloud）を最上位フィールドに持つ
  - 各 Step は provider 切替可能な形で宣言的に記述
  - 出力先（destinations）はカセットごとに柔軟に指定
  - Step の有効/無効は enabled フラグで切替
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════
# プライバシーモード定義
# ═══════════════════════════════════════════════════════════════

PrivacyMode = Literal["local", "local_llm", "cloud_batch", "cloud"]
"""
プライバシーモードと許可される外部通信:

| mode        | 外部音声API | Claude API(テキスト) | Modal GPU(バッチ) | Modal GPU(ライブ) |
|-------------|:-----------:|:--------------------:|:------------------:|:-------------------:|
| local       |      ✕      |          ✕           |         ✕          |          ✕          |
| local_llm   |      ✕      |          ◯           |         ✕          |          ✕          |
| cloud_batch |      ✕      |          ◯           |         ◯          |          ✕          |
| cloud       |      ◯      |          ◯           |         ◯          |          ◯          |
"""


# ═══════════════════════════════════════════════════════════════
# 入力 (Input)
# ═══════════════════════════════════════════════════════════════

InputType = Literal["file", "live_audio", "zoom_sdk"]
StorageBackend = Literal["local", "google_drive"]
MixMode = Literal["separate", "diarize_ready", "mono_merge"]


class AudioChannelConfig(BaseModel):
    """ライブ音声入力の 1 チャネル設定。"""

    source: Literal["microphone", "system_output"]
    label: str = Field(..., description="話者ラベル。例: self / others")


class InputConfig(BaseModel):
    """入力ソース設定。"""

    type: InputType
    storage: StorageBackend = "local"
    upload_path: str | None = Field(
        None, description="storage=google_drive の場合のアップロード先パス"
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: ["mp4", "m4a", "wav", "mp3"]
    )

    # live_audio 専用
    channels: list[AudioChannelConfig] | None = None
    mix: MixMode | None = None

    # zoom_sdk 専用（Phase 5 optional）
    source_preference: list[str] | None = Field(
        None, description="例: [zoom_sdk, system_audio] — 優先順にフォールバック"
    )

    @model_validator(mode="after")
    def validate_live_audio_fields(self) -> "InputConfig":
        if self.type == "live_audio":
            if not self.channels:
                raise ValueError("live_audio requires channels config")
            if not self.mix:
                raise ValueError("live_audio requires mix mode")
        return self


# ═══════════════════════════════════════════════════════════════
# Step 設定
# ═══════════════════════════════════════════════════════════════

StepName = Literal[
    "preprocess",
    "transcribe",
    "diarize",
    "term_correct",
    "llm_cleanup",
    "minutes_extract",
    "format",
]


class StepConfig(BaseModel):
    """パイプラインの 1 ステップ設定。"""

    step: StepName
    provider: str | None = Field(
        None,
        description=(
            "provider 例: "
            "transcribe=faster_whisper_batch | faster_whisper_chunked | whisper_streaming | whisper_cpp_coreml / "
            "diarize=pyannote | nemo / "
            "llm_cleanup=claude / "
            "minutes_extract=claude"
        ),
    )
    enabled: bool = True
    runtime: Literal["local", "modal"] = "local"
    params: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# LLM 設定
# ═══════════════════════════════════════════════════════════════


class LLMConfig(BaseModel):
    """LLM プロバイダ設定（議事録抽出・テキスト整形で利用）。"""

    provider: Literal["claude", "none"] = "claude"
    model: str = "claude-haiku-4-5"
    batch_mode: bool = Field(
        False, description="Claude Batch API を使う（50%割引、24h以内処理）"
    )
    cache_strategy: Literal["none", "system_prompt", "full"] = "system_prompt"
    max_tokens: int = 8192
    send_raw: bool = Field(
        False,
        description="True なら音声相当の生データを LLM に送る（原則 False）",
    )


# ═══════════════════════════════════════════════════════════════
# 用語辞書スタック
# ═══════════════════════════════════════════════════════════════


class TermsConfig(BaseModel):
    """用語辞書の積み重ね指定。例: [business, it, company_acme]

    後勝ちルール: リスト後方のエントリが前方を上書きする。
    ロード時に重複キー検出で warning を出す。
    """

    stack: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 出力先 (Destinations)
# ═══════════════════════════════════════════════════════════════

DestinationType = Literal["local", "notion", "slack", "email", "google_drive"]


class LocalDestination(BaseModel):
    type: Literal["local"] = "local"
    path: str = "./output/"


class NotionDestination(BaseModel):
    type: Literal["notion"] = "notion"
    database_id: str
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="Notion DB プロパティへのマッピング（Jinja2テンプレ変数で記述）",
    )


class SlackDestination(BaseModel):
    type: Literal["slack"] = "slack"
    channel: str = Field(..., description="例: '#sales-minutes'")
    post_format: Literal["summary_only", "full_minutes"] = "summary_only"


class EmailDestination(BaseModel):
    type: Literal["email"] = "email"
    to: list[str] = Field(..., description="送信先メールアドレスの固定リスト")
    cc: list[str] = Field(default_factory=list)
    subject: str = Field(..., description="Jinja2 テンプレ使用可。例: '【議事録】{{ date }}'")


class GoogleDriveDestination(BaseModel):
    type: Literal["google_drive"] = "google_drive"
    folder_path: str = Field(..., description="例: '/meetings/sales/minutes/'")


Destination = (
    LocalDestination
    | NotionDestination
    | SlackDestination
    | EmailDestination
    | GoogleDriveDestination
)


OutputFormat = Literal["md", "txt", "json", "srt"]


class OutputConfig(BaseModel):
    """出力設定。"""

    formats: list[OutputFormat] = Field(default_factory=lambda: ["md"])
    template: str | None = Field(
        None, description="Jinja2 議事録テンプレのファイルパス"
    )
    destinations: list[Destination] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# カセット本体
# ═══════════════════════════════════════════════════════════════


class CassetteConfig(BaseModel):
    """カセット定義のルートモデル。cassettes/*.yaml がこのスキーマで検証される。"""

    name: str
    description: str = ""
    mode: PrivacyMode
    input: InputConfig
    pipeline: list[StepConfig]
    llm: LLMConfig = Field(default_factory=LLMConfig)
    terms: TermsConfig = Field(default_factory=TermsConfig)
    output: OutputConfig

    # ───────────────────────────────────────────
    # プライバシーモード × 設定の整合性検証
    # ───────────────────────────────────────────

    @model_validator(mode="after")
    def validate_mode_consistency(self) -> "CassetteConfig":
        """プライバシーモードと各設定の整合性を検証する。

        違反パターンの例:
          - mode=local なのに destinations に notion/slack/email が含まれる
          - mode=local / local_llm で transcribe.provider が外部音声API
          - mode=cloud_batch で live_audio + runtime=modal（ライブ×Modalは禁止）
        """
        errors: list[str] = []

        # 外部送信を伴う destination の禁止
        external_destinations = {"notion", "slack", "email", "google_drive"}
        if self.mode == "local":
            for dest in self.output.destinations:
                if dest.type in external_destinations:
                    errors.append(
                        f"mode=local cannot use destination type '{dest.type}' "
                        f"(external communication is prohibited)"
                    )

        # 外部音声 API プロバイダの禁止（local / local_llm）
        forbidden_audio_providers = {
            "deepgram",
            "assemblyai",
            "openai_realtime",
        }
        if self.mode in ("local", "local_llm"):
            for step in self.pipeline:
                if step.step == "transcribe" and step.provider in forbidden_audio_providers:
                    errors.append(
                        f"mode={self.mode} cannot use transcribe.provider "
                        f"'{step.provider}' (external audio API is prohibited)"
                    )

        # Claude API（テキスト）の禁止
        if self.mode == "local":
            if self.llm.provider == "claude":
                errors.append("mode=local cannot use Claude API (llm.provider must be 'none')")
            for step in self.pipeline:
                if step.step in ("llm_cleanup", "minutes_extract") and step.enabled:
                    errors.append(
                        f"mode=local cannot enable step '{step.step}' "
                        f"(it requires external LLM API)"
                    )

        # Modal GPU × ライブ音声の組み合わせ禁止
        if self.input.type == "live_audio":
            for step in self.pipeline:
                if step.runtime == "modal":
                    errors.append(
                        f"input.type=live_audio cannot use runtime=modal for step '{step.step}' "
                        f"(live audio must not leave the local machine)"
                    )

        # Modal 利用は cloud_batch / cloud のみ
        if self.mode in ("local", "local_llm"):
            for step in self.pipeline:
                if step.runtime == "modal":
                    errors.append(
                        f"mode={self.mode} cannot use runtime=modal for step '{step.step}'"
                    )

        if errors:
            bullet_list = "\n  - ".join(errors)
            raise ValueError(f"Cassette privacy mode validation failed:\n  - {bullet_list}")

        return self

    # ───────────────────────────────────────────
    # 便利メソッド
    # ───────────────────────────────────────────

    def get_step(self, name: StepName) -> StepConfig | None:
        """指定した Step の設定を取得。"""
        return next((s for s in self.pipeline if s.step == name), None)

    def is_step_enabled(self, name: StepName) -> bool:
        step = self.get_step(name)
        return step is not None and step.enabled


# ═══════════════════════════════════════════════════════════════
# ローダー
# ═══════════════════════════════════════════════════════════════


def load_cassette(path: str | Path) -> CassetteConfig:
    """YAML ファイルからカセットをロードする。

    Args:
        path: カセット YAML ファイルパス

    Returns:
        検証済みの CassetteConfig

    Raises:
        FileNotFoundError: ファイルが存在しない
        ValidationError: スキーマ違反
        ValueError: プライバシーモード整合性違反
    """
    import yaml  # 遅延インポート

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Cassette file not found: {p}")

    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return CassetteConfig.model_validate(data)
