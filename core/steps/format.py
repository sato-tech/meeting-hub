"""format Step — md / txt / json / srt の出力生成。

設計（REPORT_PROMPT_B.md §3.7）:
  - md は Jinja2 テンプレ（templates/{cassette}.md.j2）でレンダリング
  - txt / json / srt は既存 transcription-pipeline の save_outputs 互換
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from core.context import Context
from core.steps.base import Step

logger = logging.getLogger(__name__)


def _srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")


def render_txt(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for s in segments:
        lines.append(f"[{float(s['start']):.1f}s] {s.get('speaker', '未割当')}:")
        lines.append(s.get("text", ""))
        lines.append("")
    return "\n".join(lines)


def render_srt(segments: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for i, s in enumerate(segments, 1):
        out.append(str(i))
        out.append(f"{_srt_time(float(s['start']))} --> {_srt_time(float(s['end']))}")
        out.append(f"{s.get('speaker', '未割当')}: {s.get('text', '')}")
        out.append("")
    return "\n".join(out)


def render_markdown(template_path: Path, ctx: Context) -> str:
    """Jinja2 で議事録 md をレンダリング。"""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    variables = {
        "cassette": ctx.cassette,
        "segments": ctx.segments,
        "minutes": ctx.minutes or {},
        "cleaned_text": ctx.cleaned_text or "",
        "speakers": sorted({s.get("speaker", "未割当") for s in ctx.segments}),
        "meta": ctx.meta,
        **(ctx.minutes or {}),  # minutes のキーを直接展開（テンプレ簡略化）
    }
    return template.render(**variables)


@Step.register("format", "default")
class FormatStep(Step):
    """各出力形式を生成して ctx.work_dir + LocalDestination.path に書く。

    params:
      include_timestamps (bool, default True)
    """

    default_provider = "default"

    def process(self, ctx: Context) -> Context:
        t0 = time.monotonic()
        out_cfg = ctx.cassette.output
        formats = list(out_cfg.formats)
        template_path = out_cfg.template
        stem = ctx.input_path.stem
        ctx.work_dir.mkdir(parents=True, exist_ok=True)

        if "md" in formats:
            if template_path:
                tp = Path(template_path)
                if not tp.is_absolute():
                    tp = Path(__file__).resolve().parents[2] / template_path
                md = render_markdown(tp, ctx)
            else:
                md = ctx.cleaned_text or render_txt(ctx.segments)
            out_path = ctx.work_dir / f"{stem}.md"
            out_path.write_text(md, encoding="utf-8")
            ctx.outputs["md"] = out_path

        if "txt" in formats:
            out_path = ctx.work_dir / f"{stem}.txt"
            out_path.write_text(render_txt(ctx.segments), encoding="utf-8")
            ctx.outputs["txt"] = out_path

        if "json" in formats:
            out_path = ctx.work_dir / f"{stem}_data.json"
            out_path.write_text(
                json.dumps(ctx.segments, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            ctx.outputs["json"] = out_path

        if "srt" in formats:
            out_path = ctx.work_dir / f"{stem}.srt"
            out_path.write_text(render_srt(ctx.segments), encoding="utf-8")
            ctx.outputs["srt"] = out_path

        ctx.record_timing("format", time.monotonic() - t0)
        logger.info("[N/N] format: %s", ", ".join(ctx.outputs.keys()))
        return ctx
