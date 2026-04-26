"""LocalAgreement-N 汎化版のテスト（T6 / A3）。

n=2 は既存挙動を維持、n=3 で 3 イテレーション合意するまで commit しないことを確認。
"""
from __future__ import annotations

from core.streaming.local_agreement import LocalAgreementState, Token, update


def _t(text: str, start: float) -> Token:
    return Token(text=text, start=start, end=start + 0.3)


# ─── 既存 n=2 挙動の担保 ──
def test_default_n_is_2():
    state = LocalAgreementState()
    assert state.n == 2


def test_n2_commits_after_second_iteration():
    state = LocalAgreementState(n=2)
    # 初回: commit なし
    first = update(state, [_t("a", 0.0), _t("b", 1.0)])
    assert first == []
    # 2 回目: 共通 prefix が commit
    second = update(state, [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0)])
    assert [t.text for t in second] == ["a", "b"]


# ─── 新規: n=3 挙動 ──
def test_n3_requires_three_consecutive_agreements():
    state = LocalAgreementState(n=3)
    # 呼び出しは「各 iter で先頭から全量の hypothesis」を渡す慣習
    # 1 回目
    assert update(state, [_t("a", 0.0), _t("b", 1.0)]) == []
    # 2 回目: n=2 なら commit されるが、n=3 では history 不足
    assert update(state, [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0)]) == []
    # 3 回目: 3 イテレーション共通の [a, b] だけ commit（c は iter1 に無いのでまだ）
    commit = update(state, [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0), _t("d", 3.0)])
    assert [t.text for t in commit] == ["a", "b"]
    # 4 回目: 全量先頭渡し。iter2/3/4 に c がある → c が commit される
    commit2 = update(
        state,
        [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0), _t("d", 3.0), _t("e", 4.0)],
    )
    assert "c" in [t.text for t in commit2]


def test_n3_rejects_disagreement_in_middle():
    state = LocalAgreementState(n=3)
    update(state, [_t("a", 0.0), _t("b", 1.0)])
    update(state, [_t("a", 0.0), _t("X", 1.0)])  # b ≠ X
    # 3 回目: a は 3 回連続一致するが b は 2 回目と違うので commit は a のみ
    commit = update(state, [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0)])
    assert [t.text for t in commit] == ["a"]


def test_n1_commits_immediately():
    """n=1 は history 不要、即 commit。"""
    state = LocalAgreementState(n=1)
    commit = update(state, [_t("a", 0.0), _t("b", 1.0)])
    assert [t.text for t in commit] == ["a", "b"]


# ─── 後方互換: last_hypothesis プロパティ ──
def test_last_hypothesis_property_backward_compat():
    state = LocalAgreementState()
    update(state, [_t("hello", 0.0), _t("world", 1.0)])
    # last_hypothesis は history の最新エントリ
    assert [t.text for t in state.last_hypothesis] == ["hello", "world"]


def test_last_hypothesis_setter_backward_compat():
    state = LocalAgreementState()
    state.last_hypothesis = [_t("x", 0.0)]
    assert [t.text for t in state.last_hypothesis] == ["x"]


# ─── history が committed 分を削って保持される ──
def test_history_drops_committed_tokens():
    state = LocalAgreementState(n=2)
    update(state, [_t("a", 0.0), _t("b", 1.0)])
    update(state, [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0)])
    # a, b は committed されたので history の最新エントリには c 以降のみが残る
    # （last_hypothesis は committed 後の tail）
    assert all(t.text not in ("a", "b") for t in state.last_hypothesis)
