"""Phase 4: 擬似リアルタイムパイプライン層。

設計要点:
  - チャンク単位（既定 20秒）で音声を切り出し、Whisper を回す
  - 重複（overlap、既定 2秒）で境界の切れ目を吸収
  - threading + queue.Queue で取り込みと推論を分離
  - 真リアルタイム化（LocalAgreement-2, whisper_streaming）は Phase 5
"""
from core.streaming.buffer import ChunkBuffer, ChunkSpec  # noqa: F401
from core.streaming.local_agreement import (  # noqa: F401
    LocalAgreementState,
    Token,
    common_prefix,
    tokens_to_segments,
    update,
)
from core.streaming.pipeline import StreamingPipeline  # noqa: F401

__all__ = [
    "ChunkBuffer",
    "ChunkSpec",
    "LocalAgreementState",
    "StreamingPipeline",
    "Token",
    "common_prefix",
    "tokens_to_segments",
    "update",
]
