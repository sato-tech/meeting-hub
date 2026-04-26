"""cassette.py の override 異常系テスト（T3 / D）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.cassette import _apply_override, load_cassette


def test_override_missing_equal_sign_raises():
    data = {"pipeline": []}
    with pytest.raises(ValueError, match="KEY=VAL"):
        _apply_override(data, "no_equals_sign")


def test_override_unknown_step_name_raises():
    """先頭が _STEP_NAMES にない単語は普通のキーとして扱われ、エラーにならず追加される。
    既存 step 名を指定して該当なしのときは KeyError。
    """
    data = {"pipeline": []}
    with pytest.raises(KeyError, match="transcribe"):
        _apply_override(data, "transcribe.params.model=x")


def test_override_pipeline_index_out_of_range():
    data = {"pipeline": []}
    with pytest.raises(IndexError):
        _apply_override(data, "pipeline[5].params.foo=bar")


def test_override_top_level_creates_missing_nested_dict():
    data = {}
    _apply_override(data, "llm.batch_mode=true")
    assert data == {"llm": {"batch_mode": True}}


def test_override_coerce_types():
    data = {}
    _apply_override(data, "a.b=42")
    _apply_override(data, "a.c=3.14")
    _apply_override(data, "a.d=true")
    _apply_override(data, "a.e=false")
    _apply_override(data, "a.f=null")
    _apply_override(data, "a.g=plain_string")
    assert data["a"] == {"b": 42, "c": 3.14, "d": True, "e": False, "f": None, "g": "plain_string"}


def test_load_cassette_nonexistent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cassette(str(tmp_path / "does_not_exist.yaml"))
