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
        cassette_name = st.selectbox("カセット", cassette_names, index=0 if cassette_names else None)

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
                st.subheader("カセット概要")
                st.write(f"**name**: `{cassette.name}`")
                st.write(f"**mode**: `{cassette.mode}` / **input.type**: `{cassette.input.type}`")
                with st.expander("Pipeline", expanded=True):
                    for s in cassette.pipeline:
                        mark = "✓" if s.enabled else "×"
                        st.write(f"{mark} **{s.step}** (provider=`{s.provider or 'default'}`)")
                with st.expander("Destinations"):
                    for d in cassette.output.destinations:
                        st.write(f"→ {d.type}")
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
        cassette_name = st.selectbox("ライブカセット", cassette_names, key="live_cassette")
        duration = st.number_input("録音時間 (秒)", min_value=10, max_value=3600, value=60, step=10)
        chunk_sec = st.slider("chunk_sec", 10.0, 30.0, 20.0, step=2.0)
        overlap_sec = st.slider("overlap_sec", 0.0, 5.0, 2.0, step=0.5)
        start = st.button("▶ ストリーム開始", type="primary", key="live_start")

    with col2:
        if cassette_name:
            try:
                cassette = load_cassette(cassette_name)
                st.write(f"**mode**: `{cassette.mode}`")
                st.write(f"**input**: `{cassette.input.type}` / mix=`{cassette.input.mix or '-'}`")
                with st.expander("Pipeline"):
                    for s in cassette.pipeline:
                        mark = "✓" if s.enabled else "×"
                        st.write(f"{mark} **{s.step}** (provider=`{s.provider}`, runtime=`{s.runtime}`)")
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
    for name in _list_cassette_names():
        path = resolve_cassette_path(name)
        with st.expander(name):
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
