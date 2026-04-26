"""meeting-hub CLI entry point.

設計: REPORT_PROMPT_B.md §6
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.adapters.file import FileAdapter
from core.adapters.live_audio import LiveAudioAdapter
from core.cassette import load_cassette
from core.pipeline import Pipeline


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="meeting-hub",
        description="統合文字起こし・議事録パイプライン（Phase 1）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("input", help="入力ファイル or ディレクトリ（--batch時）")
    p.add_argument(
        "-c", "--cassette", required=True,
        help="カセット名（例: sales_meeting）または YAML パス",
    )
    p.add_argument(
        "-o", "--output-dir", default="./output",
        help="出力ルート（デフォルト: ./output）",
    )
    p.add_argument("--batch", action="store_true", help="ディレクトリ内の対応ファイルを一括処理")
    p.add_argument("--dry-run", action="store_true", help="パイプライン構築のみ、実行しない")
    p.add_argument(
        "--override", action="append", default=[], metavar="KEY=VAL",
        help="カセット上書き（例: --override transcribe.params.beam_size=3、繰返し可）",
    )
    # エイリアス（既存CLI互換、§6.2）
    p.add_argument("--speakers", "-s", type=int, default=None,
                   help="エイリアス: --override diarize.params.num_speakers=N")
    p.add_argument("--model", default=None,
                   help="エイリアス: --override transcribe.params.model=<model>")
    p.add_argument("--denoise", action="store_true",
                   help="エイリアス: --override preprocess.params.denoise=true")
    p.add_argument("--skip-claude", action="store_true",
                   help="エイリアス: llm_cleanup/minutes_extract を無効化")
    # TTY 対話（§12-3 RESOLVED）
    p.add_argument("--no-interactive", action="store_true",
                   help="TTY 対話プロンプトを抑止")
    p.add_argument("--strict-destinations", action="store_true",
                   help="未実装 destination で exit 1（§12-4、既定 off）")
    p.add_argument("--resume", metavar="RUN_ID",
                   help="checkpoint から再開（例: --resume 20260423_153012_meeting）")
    p.add_argument("--record-seconds", type=float, default=None, metavar="SEC",
                   help="live_audio カセット用: 録音時間（秒）。未指定時は CLI 引数 input で live:// URI 指定")
    p.add_argument("--live", action="store_true",
                   help="カセットにライブプロファイル（chunked transcribe + channel_based diarize 等）"
                        "を適用。live:// URI を指定すると自動で有効化される")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG ログ")
    return p


def _prompt_num_speakers(default: int | None, lo: int = 2, hi: int = 5) -> int | None:
    if not sys.stdin.isatty():
        return default
    d_label = f"デフォルト={default}" if default else "空Enter=自動推定"
    while True:
        raw = input(f"参加人数は？ [{lo}-{hi}] ({d_label}): ").strip()
        if not raw:
            return default
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        print(f"  ⚠️  {lo}〜{hi} の数字で入力してください")


def _collect_overrides(args: argparse.Namespace) -> list[str]:
    out = list(args.override)
    if args.speakers is not None:
        out.append(f"diarize.params.num_speakers={args.speakers}")
    if args.model is not None:
        out.append(f"transcribe.params.model={args.model}")
    if args.denoise:
        out.append("preprocess.params.denoise=true")
    if args.skip_claude:
        out.append("llm_cleanup.enabled=false")
        out.append("minutes_extract.enabled=false")
    return out


def _run_single(args: argparse.Namespace, input_path: str) -> int:
    overrides = _collect_overrides(args)
    # live:// URI を検知したら自動で --live 相当を適用
    live_flag = args.live or input_path.startswith("live://")
    cassette = load_cassette(args.cassette, overrides=overrides, live=live_flag)

    # TTY 対話（§12-3）
    if (
        not args.no_interactive
        and args.speakers is None
        and cassette.get_step("diarize")
        and cassette.get_step("diarize").enabled
    ):
        diarize_cfg = cassette.get_step("diarize")
        current = diarize_cfg.params.get("num_speakers")
        chosen = _prompt_num_speakers(current)
        if chosen is not None and chosen != current:
            diarize_cfg.params["num_speakers"] = chosen
            print(f"→ 参加人数: {chosen}名で処理します")

    if args.dry_run:
        print("─── dry-run: cassette summary ───")
        print(f"name:  {cassette.name}")
        print(f"mode:  {cassette.mode}")
        for s in cassette.pipeline:
            mark = "✓" if s.enabled else "×"
            print(f"  {mark} {s.step} (provider={s.provider}) params={s.params}")
        for d in cassette.output.destinations:
            print(f"  → {d.type}")
        return 0

    # 入力アダプタの選択（カセット input.type に従う）
    if cassette.input.type == "live_audio":
        # mix を抽出（カセットで定義、既定 separate）
        mix = cassette.input.mix or "separate"
        adapter = LiveAudioAdapter(mix=mix)
        # CLI で --record-seconds が指定されれば URI に反映
        if args.record_seconds is not None and not input_path.startswith("live://"):
            input_path = f"live://duration={args.record_seconds}"
        elif not input_path.startswith("live://"):
            # live_audio カセットで file path が渡されたら一般 URI として扱う
            input_path = "live://"
    else:
        storage = cassette.input.storage
        adapter = FileAdapter(storage=storage)

    pipe = Pipeline(cassette, adapter)
    output_root = Path(args.output_dir).expanduser().resolve()
    pipe.run(
        input_path,
        output_root,
        strict_destinations=args.strict_destinations,
        resume_run_id=args.resume,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.batch:
        src = Path(args.input)
        if not src.is_dir():
            print(f"❌ ディレクトリが見つかりません: {src}", file=sys.stderr)
            return 1
        supported = ("*.mp4", "*.mp3", "*.wav", "*.m4a", "*.mov")
        files: list[Path] = []
        for pat in supported:
            files.extend(src.glob(pat))
        files = sorted(set(files))
        if not files:
            print(f"❌ 対応ファイルなし: {src}", file=sys.stderr)
            return 1
        print(f"📂 バッチ処理: {len(files)}件")
        ok = ng = 0
        for f in files:
            print(f"\n▶️  {f.name}")
            try:
                _run_single(args, str(f))
                ok += 1
            except Exception as e:
                print(f"❌ {f.name}: {e}", file=sys.stderr)
                ng += 1
        print(f"\n✅ 完了: 成功{ok} / 失敗{ng}")
        return 0 if ng == 0 else 2
    else:
        return _run_single(args, args.input)


if __name__ == "__main__":
    sys.exit(main())
