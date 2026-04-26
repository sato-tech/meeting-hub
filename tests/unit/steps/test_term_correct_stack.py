"""term_correct Step のスタックローダー / 置換ロジックテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.cassette_schema import (
    CassetteConfig,
    InputConfig,
    LocalDestination,
    OutputConfig,
    StepConfig,
    TermsConfig,
)
from core.context import Context
from core.steps.term_correct import RegexTermCorrectStep, load_term_stack


@pytest.fixture
def vocab_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vocab" / "terms"
    d.mkdir(parents=True)
    (d / "base.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "base",
                "patterns": [
                    {"match": "サース", "replace": "SaaS"},
                    {"match": "ノーション", "replace": "Notion"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "override.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "override",
                "patterns": [
                    {"match": "ノーション", "replace": "notion-client"},  # 上書き
                    {"match": "エーピーアイ", "replace": "API"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return d


def test_load_term_stack_merges_rear_wins(vocab_dir: Path) -> None:
    patterns = load_term_stack(["base", "override"], vocab_root=vocab_dir)
    # dict 化して検証
    m = dict(patterns)
    assert m["サース"] == "SaaS"
    assert m["ノーション"] == "notion-client"  # 後勝ち
    assert m["エーピーアイ"] == "API"


def test_load_term_stack_missing_file_warns_not_raises(vocab_dir: Path) -> None:
    patterns = load_term_stack(["base", "nonexistent"], vocab_root=vocab_dir)
    assert ("サース", "SaaS") in patterns


def test_term_correct_step_applies_and_counts(tmp_path, monkeypatch, vocab_dir: Path) -> None:
    monkeypatch.setattr("core.steps.term_correct._VOCAB_ROOT", vocab_dir)

    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="term_correct", provider="regex", params={})],
        terms=TermsConfig(stack=["base"]),
        output=OutputConfig(destinations=[LocalDestination()]),
    )
    ctx = Context(input_path=Path("/tmp/x.mp4"), cassette=cassette)
    ctx.segments = [
        {"start": 0.0, "end": 1.0, "text": "サースについて", "speaker": "A"},
        {"start": 1.0, "end": 2.0, "text": "ノーションを使う", "speaker": "B"},
    ]
    step = RegexTermCorrectStep(provider="regex", params={})
    step.process(ctx)

    assert ctx.segments[0]["text"] == "SaaSについて"
    assert ctx.segments[1]["text"] == "Notionを使う"
    assert ctx.meta["term_correct"]["applied_count"] == 2


def test_extra_patterns_override(monkeypatch, vocab_dir: Path) -> None:
    monkeypatch.setattr("core.steps.term_correct._VOCAB_ROOT", vocab_dir)

    cassette = CassetteConfig(
        name="test",
        mode="cloud_batch",
        input=InputConfig(type="file"),
        pipeline=[StepConfig(step="term_correct", provider="regex", params={})],
        terms=TermsConfig(stack=[]),
        output=OutputConfig(destinations=[LocalDestination()]),
    )
    ctx = Context(input_path=Path("/tmp/x.mp4"), cassette=cassette)
    ctx.segments = [{"start": 0.0, "end": 1.0, "text": "ハロー", "speaker": "A"}]
    step = RegexTermCorrectStep(
        provider="regex",
        params={"extra_patterns": [{"match": "ハロー", "replace": "Hello"}]},
    )
    step.process(ctx)
    assert ctx.segments[0]["text"] == "Hello"
