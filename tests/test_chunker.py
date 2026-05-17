import re
from pathlib import Path

import pytest

from codemind.indexing.chunker import chunk_file
from codemind.models import CodeChunk

FIXTURE = Path(__file__).parent / "fixtures" / "mini_repo" / "sample.py"


def test_chunk_count():
    chunks = chunk_file(FIXTURE)
    # 1 module + 1 function + 1 class + 2 methods
    assert len(chunks) == 5


def test_chunk_types_complete():
    types = {c.chunk_type for c in chunk_file(FIXTURE)}
    assert types == {"module", "function", "class", "method"}


def test_function_name():
    funcs = [c for c in chunk_file(FIXTURE) if c.chunk_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "hello"


def test_method_parent_name():
    methods = [c for c in chunk_file(FIXTURE) if c.chunk_type == "method"]
    assert len(methods) == 2
    assert all(m.parent_name == "Greeter" for m in methods)
    assert {m.name for m in methods} == {"__init__", "greet"}


def test_start_line_less_than_end_line():
    for c in chunk_file(FIXTURE):
        assert c.start_line < c.end_line, (
            f"{c.name}: start_line={c.start_line} >= end_line={c.end_line}"
        )


def test_chunk_id_is_16_hex():
    for c in chunk_file(FIXTURE):
        assert re.fullmatch(r"[0-9a-f]{16}", c.chunk_id), (
            f"{c.name}: invalid chunk_id={c.chunk_id!r}"
        )
