"""LocalAgreement-N アルゴリズム（Phase 5）。

Macháček et al. 2023 "Turning Whisper into Real-Time Transcription System" に基づく。
オンライン Whisper で「確定テキスト」を決める方式:

  LocalAgreement-N: 直近 N 回のイテレーションの hypothesis に **共通で現れた先頭トークン**
                    を「確定」とする。N=2 が論文の推奨。

Phase 5 では N=2 を既定とし、`LocalAgreementState(n=3)` のように引数で N を変更可能。
純粋なアルゴリズムのみを提供する（モデル呼び出しは呼出元）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

logger = logging.getLogger(__name__)


@dataclass
class Token:
    """時間付きトークン。words_timestamps で Whisper から取れるものと互換。"""
    text: str
    start: float
    end: float

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Token):
            return NotImplemented
        # 実時刻（近似）+ テキスト一致で同一判定
        return self.text == other.text and abs(self.start - other.start) < 0.5

    def __hash__(self) -> int:
        return hash((self.text, round(self.start, 1)))


@dataclass
class LocalAgreementState:
    """LocalAgreement-N のバッファ。

    n=2 (既定): 直近 2 イテレーションの共通先頭を commit
    n=3:       直近 3 イテレーション全部で合意した先頭のみ commit（より慎重）
    """

    n: int = 2
    committed: list[Token] = field(default_factory=list)
    """確定したトークン列。"""

    history: list[list[Token]] = field(default_factory=list)
    """直近 n-1 回分の hypothesis（committed 分を除いた tail 部）。"""

    # 後方互換: 旧テストが参照する `last_hypothesis` プロパティ
    @property
    def last_hypothesis(self) -> list[Token]:
        """最新の hypothesis を返す（`history[-1]`）。空なら空リスト。"""
        return self.history[-1] if self.history else []

    @last_hypothesis.setter
    def last_hypothesis(self, value: list[Token]) -> None:
        """旧 API 互換: 単一 hypothesis の代入を history の最新エントリ更新として扱う。"""
        if self.history:
            self.history[-1] = list(value)
        else:
            self.history.append(list(value))

    def commit_text(self) -> str:
        return " ".join(t.text for t in self.committed)

    def hypothesis_text(self) -> str:
        return " ".join(t.text for t in self.last_hypothesis)


def common_prefix(*sequences: Sequence[Token]) -> list[Token]:
    """任意個数のトークン列の共通先頭を返す。"""
    if not sequences:
        return []
    out: list[Token] = []
    for tokens in zip(*sequences):
        first = tokens[0]
        if all(t == first for t in tokens[1:]):
            out.append(first)
        else:
            break
    return out


def update(state: LocalAgreementState, new_hypothesis: list[Token]) -> list[Token]:
    """新しい transcribe 結果で state を更新し、新たに commit されたトークンを返す。

    LocalAgreement-N アルゴリズム:
      1. committed 分を new の先頭から剥がす
      2. state.history（直近 n-1 回分）+ 今回の tail_new の全てで合意した先頭を commit
      3. history に今回の tail_new を追加、古いものを drop
      4. state.committed に追加
    """
    committed_len = len(state.committed)
    tail_new = (
        new_hypothesis[committed_len:] if len(new_hypothesis) >= committed_len else []
    )

    # history に n-1 個以上の hypothesis が溜まっていれば N-agreement を計算
    required_history = state.n - 1
    if len(state.history) >= required_history and required_history > 0:
        sequences = list(state.history[-required_history:]) + [tail_new]
        newly_committed = common_prefix(*sequences)
    elif required_history == 0:
        # n=1 の極端ケース: 即 commit
        newly_committed = list(tail_new)
    else:
        # history 不足: まだ commit しない
        newly_committed = []

    state.committed.extend(newly_committed)

    # history を更新: 新 tail を追加、古いものを drop
    # committed で削った分だけ各 history entry からも先頭を削る必要がある
    drop_len = len(newly_committed)
    if drop_len > 0:
        state.history = [
            h[drop_len:] if len(h) >= drop_len else []
            for h in state.history
        ]
    state.history.append(tail_new[drop_len:] if len(tail_new) >= drop_len else [])

    # history サイズを n-1 に制限
    if len(state.history) > required_history and required_history > 0:
        state.history = state.history[-required_history:]

    return newly_committed


def tokens_to_segments(tokens: Sequence[Token], *, merge_gap_sec: float = 0.8) -> list[dict]:
    """Token 列を `[{start, end, text, speaker}]` の segment 列にまとめる。

    gap が `merge_gap_sec` 以下なら同じ segment に連結する。
    """
    if not tokens:
        return []
    segments: list[dict] = []
    current = {"start": tokens[0].start, "end": tokens[0].end, "text": tokens[0].text, "speaker": "未割当"}
    for tok in tokens[1:]:
        if tok.start - current["end"] <= merge_gap_sec:
            current["end"] = tok.end
            current["text"] = f"{current['text']} {tok.text}".strip()
        else:
            segments.append(current)
            current = {"start": tok.start, "end": tok.end, "text": tok.text, "speaker": "未割当"}
    segments.append(current)
    return segments
