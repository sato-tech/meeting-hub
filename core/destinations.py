"""出力先 (Destinations) — パイプライン成果物の配信。

Providers:
  - local:         ctx.outputs をローカルディレクトリにコピー
  - notion:        Notion DB にページ作成（notion-client）
  - slack:         Slack に投稿 / md をアップロード（slack-sdk）
  - email:         Gmail SMTP で送信（標準 smtplib + app password）
  - google_drive:  サービスアカウントでアップロード
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

from jinja2 import Environment

from core.cassette_schema import Destination as DestCfg  # noqa: F401 (re-export)
from core.context import Context

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Destination ABC とレジストリ
# ═══════════════════════════════════════════════════
class Destination(ABC):
    _registry: ClassVar[dict[str, type["Destination"]]] = {}

    def __init__(self, config: Any):
        self.config = config

    @abstractmethod
    def send(self, ctx: Context) -> None: ...

    @classmethod
    def register(cls, type_name: str):
        def deco(sub: type[Destination]) -> type[Destination]:
            cls._registry[type_name] = sub
            return sub
        return deco

    @classmethod
    def create(cls, cfg: Any) -> "Destination":
        if cfg.type not in cls._registry:
            raise ValueError(f"No Destination registered for type={cfg.type!r}")
        return cls._registry[cfg.type](cfg)


# ═══════════════════════════════════════════════════
# Local
# ═══════════════════════════════════════════════════
@Destination.register("local")
class LocalDestinationImpl(Destination):
    def send(self, ctx: Context) -> None:
        dest_dir = Path(self.config.path).expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        for kind, src in ctx.outputs.items():
            dst = dest_dir / src.name
            shutil.copy2(src, dst)
            logger.info("[local] %s → %s", kind, dst)


# ═══════════════════════════════════════════════════
# Notion（notion-client）
# ═══════════════════════════════════════════════════
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: str) -> str:
    """`${NOTION_DB_SALES}` のような参照を環境変数から展開。"""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        val = os.environ.get(key)
        if val is None:
            raise EnvironmentError(f"env var {key} is not set (referenced by cassette)")
        return val
    return _ENV_REF.sub(sub, value)


def _render_template(template: str, minutes: dict, meta: dict) -> str:
    """Jinja2 の `{{ key }}` を minutes / meta から単純展開。"""
    env = Environment(autoescape=False)
    tpl = env.from_string(template)
    return tpl.render(**minutes, meta=meta)


def _build_properties(property_map: dict[str, str], minutes: dict, meta: dict) -> dict[str, Any]:
    """Notion DB の properties 構造を構築。"""
    props: dict[str, Any] = {}
    first = True
    for prop_name, template in property_map.items():
        value = _render_template(template, minutes, meta)
        key_lower = prop_name.lower()
        if first:
            props[prop_name] = {"title": [{"text": {"content": value[:2000]}}]}
            first = False
        elif "date" in key_lower:
            props[prop_name] = {"date": {"start": value}}
        else:
            props[prop_name] = {"rich_text": [{"text": {"content": value[:2000]}}]}
    return props


@Destination.register("notion")
class NotionDestinationImpl(Destination):
    """Notion DB にページを作成。"""

    def send(self, ctx: Context) -> None:
        token = os.environ.get("NOTION_API_KEY")
        if not token:
            raise EnvironmentError("NOTION_API_KEY is not set")

        try:
            from notion_client import Client  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("notion-client not installed. `pip install notion-client`")

        database_id = _expand_env(self.config.database_id)
        minutes = ctx.minutes or {}
        meta = ctx.meta or {}
        props = _build_properties(self.config.properties or {}, minutes, meta)

        client = Client(auth=token)
        resp = client.pages.create(parent={"database_id": database_id}, properties=props)
        page_id = resp.get("id")
        logger.info("[notion] created page %s in db %s", page_id, database_id)
        ctx.meta.setdefault("destinations", {}).setdefault("notion", []).append(
            {"database_id": database_id, "page_id": page_id}
        )


# ═══════════════════════════════════════════════════
# Slack（slack-sdk）
# ═══════════════════════════════════════════════════
@Destination.register("slack")
class SlackDestinationImpl(Destination):
    """post_format: summary_only | full_minutes"""

    def send(self, ctx: Context) -> None:
        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            raise EnvironmentError("SLACK_BOT_TOKEN is not set")

        try:
            from slack_sdk import WebClient  # type: ignore[import-not-found]
            from slack_sdk.errors import SlackApiError  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("slack-sdk not installed. `pip install slack-sdk`")

        channel = self.config.channel
        post_format = getattr(self.config, "post_format", "summary_only")
        minutes = ctx.minutes or {}
        client = WebClient(token=token)

        if post_format == "summary_only":
            text = self._build_summary_text(minutes)
            try:
                resp = client.chat_postMessage(channel=channel, text=text)
                logger.info("[slack] posted to %s (ts=%s)", channel, resp.get("ts"))
                self._record(ctx, channel, resp.get("ts"))
            except SlackApiError as e:
                raise RuntimeError(f"Slack postMessage failed: {e.response['error']}") from e
        else:
            md_path = ctx.outputs.get("md")
            if md_path is None:
                logger.warning("[slack] no md output to upload; falling back to summary")
                text = self._build_summary_text(minutes)
                client.chat_postMessage(channel=channel, text=text)
                return
            try:
                resp = client.files_upload_v2(
                    channel=channel,
                    file=str(md_path),
                    title=minutes.get("meeting_title") or md_path.stem,
                    initial_comment=self._build_summary_text(minutes),
                )
                logger.info("[slack] uploaded %s to %s", md_path.name, channel)
                self._record(ctx, channel, resp.get("ts"))
            except SlackApiError as e:
                raise RuntimeError(f"Slack files_upload failed: {e.response['error']}") from e

    @staticmethod
    def _build_summary_text(minutes: dict[str, Any]) -> str:
        title = minutes.get("meeting_title") or minutes.get("title") or "議事録"
        date = minutes.get("date") or ""
        summary = minutes.get("summary_3lines") or ""
        parts = [f"*{title}*"]
        if date:
            parts.append(f"_{date}_")
        if summary:
            parts.append(summary)
        return "\n".join(parts)

    @staticmethod
    def _record(ctx: Context, channel: str, ts: Any) -> None:
        ctx.meta.setdefault("destinations", {}).setdefault("slack", []).append(
            {"channel": channel, "ts": ts}
        )


# ═══════════════════════════════════════════════════
# Email（Gmail SMTP + app password）
# ═══════════════════════════════════════════════════
@Destination.register("email")
class EmailDestinationImpl(Destination):
    def send(self, ctx: Context) -> None:
        user = os.environ.get("GMAIL_USER")
        password = os.environ.get("GMAIL_APP_PASSWORD")
        if not user or not password:
            raise EnvironmentError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")

        minutes = ctx.minutes or {}
        subject_tpl = self.config.subject or "【議事録】"
        subject = Environment(autoescape=False).from_string(subject_tpl).render(**minutes)

        body = self._build_body(ctx)
        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = ", ".join(self.config.to)
        if self.config.cc:
            msg["Cc"] = ", ".join(self.config.cc)
        msg["Subject"] = subject
        msg.set_content(body)

        md_path: Path | None = ctx.outputs.get("md")
        if md_path and md_path.exists():
            msg.add_attachment(
                md_path.read_bytes(),
                maintype="text",
                subtype="markdown",
                filename=md_path.name,
            )

        recipients = list(self.config.to) + list(self.config.cc or [])
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg, from_addr=user, to_addrs=recipients)
        logger.info("[email] sent to %d recipient(s): subject=%r", len(recipients), subject)
        ctx.meta.setdefault("destinations", {}).setdefault("email", []).append(
            {"subject": subject, "recipients": recipients}
        )

    @staticmethod
    def _build_body(ctx: Context) -> str:
        minutes = ctx.minutes or {}
        title = minutes.get("meeting_title") or minutes.get("title") or ""
        date = minutes.get("date") or ""
        summary = minutes.get("summary_3lines") or ""
        cleaned = ctx.cleaned_text or ""
        parts = []
        if title:
            parts.append(f"【{title}】")
        if date:
            parts.append(f"日付: {date}")
        if summary:
            parts.append("")
            parts.append("■ サマリ")
            parts.append(summary)
        if cleaned:
            parts.append("")
            parts.append("■ 議事")
            parts.append(cleaned[:5000])
            if len(cleaned) > 5000:
                parts.append("... (省略。全文は添付 md を参照)")
        return "\n".join(parts)


# ═══════════════════════════════════════════════════
# Google Drive（service account upload）
# ═══════════════════════════════════════════════════
@Destination.register("google_drive")
class GoogleDriveDestinationImpl(Destination):
    """ctx.outputs を指定 Drive フォルダにアップロード。

    folder_path は `drive-folder://<folderId>` 形式推奨。パス形式は解決不可として skip。
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def send(self, ctx: Context) -> None:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path:
            raise EnvironmentError("GOOGLE_APPLICATION_CREDENTIALS is not set")

        folder_path = self.config.folder_path or ""
        folder_id = self._resolve_folder_id(folder_path)
        if folder_id is None:
            ctx.add_warning(
                f"google_drive: cannot resolve folder from {folder_path!r}. "
                "Use `drive-folder://<id>` format."
            )
            logger.warning("[google_drive] skipped — cannot resolve folder from %r", folder_path)
            return

        from google.oauth2 import service_account  # type: ignore[import-not-found]
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
        from googleapiclient.http import MediaFileUpload  # type: ignore[import-not-found]

        creds = service_account.Credentials.from_service_account_file(cred_path, scopes=self.SCOPES)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        uploaded: list[dict] = []
        for kind, path in ctx.outputs.items():
            mimetype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            media = MediaFileUpload(str(path), mimetype=mimetype)
            meta = {"name": path.name, "parents": [folder_id]}
            created = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
            uploaded.append({"name": path.name, "id": created["id"], "link": created.get("webViewLink")})
            logger.info("[google_drive] uploaded %s → %s", path.name, created["id"])

        ctx.meta.setdefault("destinations", {}).setdefault("google_drive", []).extend(uploaded)

    @staticmethod
    def _resolve_folder_id(folder_path: str) -> str | None:
        if folder_path.startswith("drive-folder://"):
            return folder_path[len("drive-folder://"):]
        if re.fullmatch(r"[A-Za-z0-9_-]{20,}", folder_path):
            return folder_path
        return None


__all__ = [
    "Destination",
    "LocalDestinationImpl",
    "NotionDestinationImpl",
    "SlackDestinationImpl",
    "EmailDestinationImpl",
    "GoogleDriveDestinationImpl",
]
