"""Streamlit Web UI（Phase 3）。

起動方法:
  streamlit run web/streamlit_app.py

環境変数:
  AUTH_MODE: noauth | basic | google
  AUTH_USERS: `alice:pw:admin,bob:pw:user` （AUTH_MODE=basic のとき）
  MEETING_HUB_OUTPUT_DIR: 出力ルート（既定 ./output）
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# リポジトリルートを sys.path に
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core.cassette import load_cassette, resolve_cassette_path  # noqa: E402
from core.history import JobHistory  # noqa: E402
from web.auth import create_default_provider, BasicAuthProvider  # noqa: E402
from web.run_service import RunService  # noqa: E402


# ═══════════════════════════════════════════
# セットアップ
# ═══════════════════════════════════════════
st.set_page_config(page_title="meeting-hub", page_icon="🎙️", layout="wide")

CASSETTES_DIR = ROOT / "cassettes"
OUTPUT_ROOT = Path(os.environ.get("MEETING_HUB_OUTPUT_DIR") or ROOT / "output").expanduser()
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


@st.cache_resource
def get_history() -> JobHistory:
    return JobHistory()


@st.cache_resource
def get_run_service() -> RunService:
    return RunService(get_history(), OUTPUT_ROOT)


@st.cache_resource
def get_auth_provider():
    return create_default_provider()


def _list_cassette_names() -> list[str]:
    return sorted(p.stem for p in CASSETTES_DIR.glob("*.yaml"))


# ═══════════════════════════════════════════
# 日本語ラベル
# ═══════════════════════════════════════════
_STEP_LABELS_JA: dict[str, tuple[str, str]] = {
    "preprocess":      ("前処理",        "ノイズ除去・サンプリング調整"),
    "transcribe":      ("文字起こし",     "Whisper などで音声 → テキスト"),
    "diarize":         ("話者分離",      "発話者ごとにセグメント分割"),
    "term_correct":    ("用語補正",      "業界用語・固有名詞の表記統一"),
    "llm_cleanup":     ("整形（LLM）",   "フィラー除去・文の整形"),
    "minutes_extract": ("議事録抽出",     "Claude で要約・決定事項・ToDo を抽出"),
    "format":          ("出力整形",      "Markdown / JSON へ整形"),
}

_DESTINATION_LABELS_JA: dict[str, str] = {
    "local":        "ローカル保存",
    "google_drive": "Google Drive",
    "notion":       "Notion DB",
    "slack":        "Slack",
    "email":        "メール送信",
}

_MODE_LABELS_JA: dict[str, str] = {
    "cloud_batch": "クラウドバッチ（Modal GPU + Claude API 利用可）",
    "local":       "ローカル完結（外部送信なし）",
    "local_llm":   "ローカル + Claude API のみ（外部音声API禁止）",
    "live":        "ライブ（リアルタイム）",
}


@st.cache_data
def _cassette_meta(name: str) -> dict | None:
    """カセット表示用メタ情報。失敗時は None。"""
    try:
        c = load_cassette(name)
        return {
            "name": c.name,
            "description": c.description or "",
            "mode": str(c.mode),
        }
    except Exception:
        return None


def _format_cassette_option(name: str) -> str:
    """selectbox 用のラベル: 「説明文〔internal_meeting〕」形式。"""
    meta = _cassette_meta(name)
    if meta and meta["description"]:
        return f"{meta['description']}  〔{name}〕"
    return name


def _render_cassette_detail(cassette) -> None:
    """カセット詳細パネル（日本語ラベル付き）。"""
    if cassette.description:
        st.markdown(f"### {cassette.description}")
    st.caption(f"カセットID: `{cassette.name}`")

    mode_label = _MODE_LABELS_JA.get(str(cassette.mode), str(cassette.mode))
    st.write(f"**実行モード**: {mode_label}")
    st.write(f"**入力種別**: `{cassette.input.type}`"
             + (f" / mix=`{cassette.input.mix}`" if getattr(cassette.input, "mix", None) else ""))

    with st.expander("処理パイプライン", expanded=True):
        for s in cassette.pipeline:
            mark = "✓" if s.enabled else "×"
            label_ja, hint_ja = _STEP_LABELS_JA.get(s.step, (s.step, ""))
            provider = s.provider or "default"
            line = f"{mark} **{label_ja}**  — {hint_ja}" if hint_ja else f"{mark} **{label_ja}**"
            st.markdown(line)
            st.caption(f"step=`{s.step}` / provider=`{provider}` / runtime=`{getattr(s, 'runtime', '-')}`")

    with st.expander("出力先（Destinations）", expanded=False):
        for d in cassette.output.destinations:
            label_ja = _DESTINATION_LABELS_JA.get(d.type, d.type)
            st.write(f"→ **{label_ja}** (`{d.type}`)")


# ═══════════════════════════════════════════
# 認証
# ═══════════════════════════════════════════
def login_view() -> None:
    provider = get_auth_provider()
    st.title("🎙️ meeting-hub")
    st.caption("Sign in")

    if isinstance(provider, BasicAuthProvider):
        with st.form("login"):
            name = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
        if submitted:
            user = provider.authenticate({"name": name, "password": pw})
            if user is None:
                st.error("Invalid username or password")
            else:
                st.session_state["user"] = user
                st.rerun()
    else:
        # NoAuth / Google SSO
        name = st.text_input("Display name (optional)", value="local")
        if st.button("Enter"):
            user = provider.authenticate({"name": name})
            if user:
                st.session_state["user"] = user
                st.rerun()


def current_user():
    return st.session_state.get("user")


# ═══════════════════════════════════════════
# ページ: Run
# ═══════════════════════════════════════════
def page_run() -> None:
    user = current_user()
    st.header("🎯 新規ジョブ")

    col_left, col_right = st.columns([2, 3])

    with col_left:
        cassette_names = _list_cassette_names()
        cassette_name = st.selectbox(
            "カセット（用途別プリセット）",
            cassette_names,
            index=0 if cassette_names else None,
            format_func=_format_cassette_option,
            help="用途ごとに最適化された処理パイプラインのプリセットです。",
        )

        input_mode = st.radio("入力モード", ["file upload", "live audio"], horizontal=True)

        uploaded = None
        live_duration = 60
        if input_mode == "file upload":
            uploaded = st.file_uploader("音声/動画ファイル", type=["mp4", "m4a", "mp3", "wav", "mov"])
        else:
            live_duration = st.number_input("録音時間 (秒)", min_value=10, max_value=3600, value=60, step=10)
            st.info("BlackHole (macOS) / VB-Cable (Windows) の事前設定が必要です。docs/SETUP_LIVE_AUDIO_*.md を参照")

        with st.expander("上書き (override)", expanded=False):
            overrides_text = st.text_area(
                "KEY=VAL を 1 行ごとに（例: transcribe.params.beam_size=3）",
                value="",
                height=120,
            )

        run_clicked = st.button("▶️ 実行", type="primary", disabled=(uploaded is None and input_mode == "file upload"))

    with col_right:
        if cassette_name:
            try:
                cassette = load_cassette(cassette_name)
                _render_cassette_detail(cassette)
            except Exception as e:
                st.error(f"カセットロード失敗: {e}")

    if run_clicked:
        svc = get_run_service()
        overrides = [line.strip() for line in overrides_text.splitlines() if line.strip() and "=" in line]
        if input_mode == "file upload" and uploaded is not None:
            # 一時保存
            tmp = OUTPUT_ROOT / "_uploads"
            tmp.mkdir(parents=True, exist_ok=True)
            saved = tmp / uploaded.name
            saved.write_bytes(uploaded.getvalue())
            job_id = svc.start_job(
                user_id=user.id,
                cassette_name=cassette_name,
                input_path=saved,
                overrides=overrides,
            )
        else:
            uri = f"live://duration={int(live_duration)}"
            job_id = svc.start_job(
                user_id=user.id,
                cassette_name=cassette_name,
                input_path=uri,
                overrides=overrides,
            )
        st.success(f"ジョブ起動: `{job_id}`")
        st.session_state["watch_job_id"] = job_id
        st.rerun()

    # 直近ジョブの進捗
    wjob = st.session_state.get("watch_job_id")
    if wjob:
        st.divider()
        _render_progress(wjob)


def _render_progress(job_id: str) -> None:
    history = get_history()
    rec = history.get(job_id)
    if not rec:
        return
    st.subheader(f"進捗: `{rec.run_id}`")
    status_label = {"pending": "⏳", "running": "⚙️", "completed": "✅", "failed": "❌"}.get(rec.status, "?")
    st.write(f"{status_label} status = **{rec.status}** / cassette = `{rec.cassette}`")

    cp_dir = Path(rec.work_dir) / "checkpoints"
    if cp_dir.exists():
        done_steps = sorted(p.stem for p in cp_dir.glob("*.json") if "_" not in p.stem)
        st.write("完了 Step:", ", ".join(done_steps) if done_steps else "(まだなし)")

    # 完了していれば出力一覧
    if rec.status in ("completed", "failed"):
        work = Path(rec.work_dir)
        if work.exists():
            files = [p for p in work.iterdir() if p.is_file()]
            if files:
                st.write("**出力ファイル**")
                for f in files:
                    with open(f, "rb") as fh:
                        st.download_button(label=f.name, data=fh.read(), file_name=f.name, key=str(f))

    # 実行中なら自動リフレッシュ
    if rec.status in ("pending", "running"):
        time.sleep(1.0)
        st.rerun()


# ═══════════════════════════════════════════
# ページ: History
# ═══════════════════════════════════════════
def page_history() -> None:
    user = current_user()
    history = get_history()
    st.header("📜 ジョブ履歴")
    limit = st.slider("表示件数", 10, 200, 50)
    show_all = st.checkbox("全員分を表示 (admin)", value=False, disabled=not user.is_admin)
    jobs = history.list(user_id=user.id, limit=limit, include_all=show_all and user.is_admin)

    if not jobs:
        st.info("まだジョブがありません")
        return

    for rec in jobs:
        label = {"completed": "✅", "running": "⚙️", "failed": "❌", "pending": "⏳"}.get(rec.status, "?")
        with st.expander(f"{label} {rec.run_id}  ({rec.cassette}, {rec.user_id})"):
            c1, c2 = st.columns([2, 3])
            with c1:
                st.write(f"**run_id**: `{rec.run_id}`")
                st.write(f"**status**: `{rec.status}`")
                st.write(f"**started**: {rec.started_at}")
                st.write(f"**finished**: {rec.finished_at or '-'}")
                st.write(f"**work_dir**: `{rec.work_dir}`")
            with c2:
                events = history.list_events(rec.id)
                if events:
                    st.write("**Step events**")
                    for ev in events[-30:]:
                        detail = ev.get("detail") or {}
                        elapsed = detail.get("elapsed_sec")
                        extra = f" ({elapsed:.1f}s)" if isinstance(elapsed, (int, float)) else ""
                        st.write(f"- `{ev['at']}` {ev['step']}/{ev['event']}{extra}")
                if rec.meta:
                    with st.expander("meta"):
                        st.json(rec.meta)

            if rec.status == "completed":
                from pathlib import Path as _P
                work = _P(rec.work_dir)
                if work.exists():
                    for f in work.iterdir():
                        if f.is_file():
                            st.download_button(
                                label=f"⬇ {f.name}",
                                data=f.read_bytes(),
                                file_name=f.name,
                                key=f"dl-{rec.id}-{f.name}",
                            )
            if (user.is_admin or rec.user_id == user.id):
                if st.button(f"🗑 削除", key=f"del-{rec.id}"):
                    history.delete(rec.id)
                    st.rerun()


# ═══════════════════════════════════════════
# ページ: Live (Phase 4: 擬似ストリーム)
# ═══════════════════════════════════════════
def page_live() -> None:
    user = current_user()
    st.header("🔴 Live（擬似ストリーム）")
    st.caption("ライブ音声を取り込み、チャンク毎に部分文字起こしを表示します。")

    cassette_names = [n for n in _list_cassette_names() if n.startswith("live_") or n == "one_on_one_live"]
    if not cassette_names:
        st.info("ライブ用カセットがありません")
        return

    col1, col2 = st.columns([2, 3])
    with col1:
        cassette_name = st.selectbox(
            "ライブカセット",
            cassette_names,
            key="live_cassette",
            format_func=_format_cassette_option,
        )
        duration = st.number_input("録音時間 (秒)", min_value=10, max_value=3600, value=60, step=10)
        chunk_sec = st.slider("chunk_sec", 10.0, 30.0, 20.0, step=2.0)
        overlap_sec = st.slider("overlap_sec", 0.0, 5.0, 2.0, step=0.5)
        start = st.button("▶ ストリーム開始", type="primary", key="live_start")

    with col2:
        if cassette_name:
            try:
                cassette = load_cassette(cassette_name)
                _render_cassette_detail(cassette)
            except Exception as e:
                st.error(f"カセットロード失敗: {e}")

    if start:
        from core.adapters.live_audio import LiveAudioAdapter
        from core.streaming.pipeline import StreamingPipeline
        from core.cassette import load_cassette as _load

        st.session_state["live_partials"] = []
        st.session_state["live_running"] = True

        cassette = _load(
            cassette_name,
            overrides=[
                f"transcribe.params.chunk_sec={chunk_sec}",
                f"transcribe.params.overlap_sec={overlap_sec}",
            ],
        )
        adapter = LiveAudioAdapter(mix=cassette.input.mix or "separate")
        pipe = StreamingPipeline(
            cassette,
            adapter,
            on_partial=lambda segs: st.session_state["live_partials"].extend(segs),
        )
        uri = f"live://duration={int(duration)}"
        job = pipe.run_async(uri, OUTPUT_ROOT)
        st.session_state["live_job"] = job
        st.success("録音開始。完了までそのままお待ちください（録音中は sounddevice が音声を取得します）。")
        st.rerun()

    if st.session_state.get("live_running"):
        job = st.session_state.get("live_job")
        if job is None:
            st.session_state["live_running"] = False
            return

        st.divider()
        st.write(f"**partial segments** ({len(st.session_state.get('live_partials', []))})")
        for seg in st.session_state.get("live_partials", [])[-50:]:
            st.write(f"`[{seg['start']:.1f}-{seg['end']:.1f}s]` **{seg.get('speaker', '?')}**: {seg['text']}")

        if job.done:
            st.session_state["live_running"] = False
            st.success("✅ 完了しました")
            try:
                ctx = job.wait(timeout=1.0)
                st.write(f"**run_id**: `{ctx.run_id}`")
                st.write(f"**final segments**: {len(ctx.segments)}")
                for kind, path in ctx.outputs.items():
                    from pathlib import Path as _P
                    p = _P(path) if not isinstance(path, _P) else path
                    if p.exists():
                        with p.open("rb") as fh:
                            st.download_button(
                                label=f"⬇ {p.name}",
                                data=fh.read(),
                                file_name=p.name,
                                key=f"live-dl-{p.name}",
                            )
            except Exception as e:
                st.error(f"エラー: {e}")
        else:
            time.sleep(1.0)
            st.rerun()


# ═══════════════════════════════════════════
# ページ: Cassettes (admin)
# ═══════════════════════════════════════════
def page_cassettes() -> None:
    user = current_user()
    if not user.is_admin:
        st.warning("管理者権限が必要です")
        return
    st.header("🗂️ カセット")
    st.caption("用途ごとに最適化された処理パイプラインのプリセット一覧です。")
    for name in _list_cassette_names():
        path = resolve_cassette_path(name)
        meta = _cassette_meta(name)
        label = f"{meta['description']}  〔{name}〕" if meta and meta["description"] else name
        with st.expander(label):
            try:
                cassette = load_cassette(name)
                _render_cassette_detail(cassette)
                st.divider()
                st.caption("YAML 定義（生データ）")
            except Exception as e:
                st.error(f"カセットロード失敗: {e}")
            st.code(path.read_text(encoding="utf-8"), language="yaml")


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main() -> None:
    user = current_user()
    if user is None:
        login_view()
        return

    with st.sidebar:
        st.header("🎙️ meeting-hub")
        st.caption(f"👤 {user.name} ({user.role})")
        page = st.radio("ページ", ["Run", "Live", "History", "Cassettes"], label_visibility="collapsed")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()

    if page == "Run":
        page_run()
    elif page == "Live":
        page_live()
    elif page == "History":
        page_history()
    elif page == "Cassettes":
        page_cassettes()


if __name__ == "__main__":
    main()
