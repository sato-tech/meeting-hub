"""Step 実装群。

各サブモジュールの import で `@Step.register(...)` が実行され、
`Step.create(step_cfg)` から取り出せるようになる。
"""
# M1-M6 で順次 import を追加。明示 import がレジストリ登録を走らせる。
from core.steps import preprocess  # noqa: F401
from core.steps import transcribe  # noqa: F401
from core.steps import diarize  # noqa: F401
from core.steps import term_correct  # noqa: F401
from core.steps import llm_cleanup  # noqa: F401
from core.steps import minutes_extract  # noqa: F401
from core.steps import format as format_step  # noqa: F401

__all__ = [
    "preprocess",
    "transcribe",
    "diarize",
    "term_correct",
    "llm_cleanup",
    "minutes_extract",
    "format_step",
]
