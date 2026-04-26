"""LocalAgreement-2 の純アルゴリズムテスト（モデル非依存）。"""
from __future__ import annotations

from core.streaming.local_agreement import (
    LocalAgreementState,
    Token,
    common_prefix,
    tokens_to_segments,
    update,
)


def _t(text: str, start: float, end: float | None = None) -> Token:
    return Token(text=text, start=start, end=end if end is not None else start + 0.3)


def test_token_equality_allows_timestamp_jitter():
    # 0.5 秒未満のズレは同一扱い
    assert _t("hello", 1.0) == _t("hello", 1.3)
    # テキスト違いは不一致
    assert _t("hello", 1.0) != _t("world", 1.0)
    # 大きく違う時刻は不一致
    assert _t("hello", 1.0) != _t("hello", 2.5)


def test_common_prefix():
    a = [_t("a", 0.0), _t("b", 1.0), _t("c", 2.0)]
    b = [_t("a", 0.0), _t("b", 1.0), _t("z", 2.0)]
    pref = common_prefix(a, b)
    assert [p.text for p in pref] == ["a", "b"]


def test_common_prefix_empty():
    assert common_prefix([_t("a", 0.0)], [_t("b", 0.0)]) == []


def test_update_first_iteration_commits_nothing():
    """初回は last_hypothesis が空なので何も commit されない。"""
    state = LocalAgreementState()
    newly = update(state, [_t("hello", 0.0), _t("world", 1.0)])
    assert newly == []
    assert state.committed == []
    assert len(state.last_hypothesis) == 2


def test_update_second_iteration_commits_common_prefix():
    state = LocalAgreementState()
    update(state, [_t("hello", 0.0), _t("world", 1.0)])
    # 2回目: "hello", "world" は変わらないので commit される
    newly = update(state, [_t("hello", 0.0), _t("world", 1.0), _t("friend", 2.0)])
    assert [t.text for t in newly] == ["hello", "world"]
    assert [t.text for t in state.committed] == ["hello", "world"]
    assert [t.text for t in state.last_hypothesis] == ["friend"]


def test_update_when_disagreement():
    state = LocalAgreementState()
    update(state, [_t("a", 0.0), _t("b", 1.0)])
    # 2回目: 先頭だけ一致
    newly = update(state, [_t("a", 0.0), _t("c", 1.0)])
    assert [t.text for t in newly] == ["a"]
    assert [t.text for t in state.committed] == ["a"]


def test_update_progressive_commit_across_iterations():
    state = LocalAgreementState()
    update(state, [_t("the", 0.0)])
    update(state, [_t("the", 0.0), _t("cat", 0.5)])  # commit "the"
    update(state, [_t("the", 0.0), _t("cat", 0.5), _t("sat", 1.0)])  # commit "cat"
    assert [t.text for t in state.committed] == ["the", "cat"]
    assert [t.text for t in state.last_hypothesis] == ["sat"]


def test_tokens_to_segments_merges_close_tokens():
    tokens = [_t("hello", 0.0, 0.5), _t("world", 0.7, 1.2)]
    segs = tokens_to_segments(tokens, merge_gap_sec=0.5)
    assert len(segs) == 1
    assert segs[0]["text"] == "hello world"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 1.2


def test_tokens_to_segments_splits_on_big_gap():
    tokens = [_t("a", 0.0, 0.3), _t("b", 5.0, 5.3)]
    segs = tokens_to_segments(tokens, merge_gap_sec=0.5)
    assert len(segs) == 2
    assert segs[0]["text"] == "a"
    assert segs[1]["text"] == "b"


def test_tokens_to_segments_empty():
    assert tokens_to_segments([]) == []


def test_commit_text_and_hypothesis_text():
    state = LocalAgreementState()
    update(state, [_t("hello", 0.0), _t("world", 1.0)])
    update(state, [_t("hello", 0.0), _t("world", 1.0), _t("friend", 2.0)])
    assert state.commit_text() == "hello world"
    assert state.hypothesis_text() == "friend"
