import re
from pathlib import Path

import pytest

from codemind.exceptions import ParserError
from codemind.indexing.chunker import chunk_file
from codemind.models import CodeChunk

FIXTURE = Path(__file__).parent / "fixtures" / "mini_repo" / "sample.py"
FIXTURE_TS = Path(__file__).parent / "fixtures" / "mini_repo" / "sample.ts"
FIXTURE_JAVA = Path(__file__).parent / "fixtures" / "mini_repo" / "Sample.java"
FIXTURE_GO = Path(__file__).parent / "fixtures" / "mini_repo" / "sample.go"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------

def test_ts_chunk_count():
    chunks = chunk_file(FIXTURE_TS)
    # 1 function + 1 class + 2 methods (constructor + hello)
    assert len(chunks) == 4


def test_ts_chunk_types():
    types = {c.chunk_type for c in chunk_file(FIXTURE_TS)}
    assert "function" in types
    assert "class" in types
    assert "method" in types
    assert "module" not in types


def test_ts_function_name():
    funcs = [c for c in chunk_file(FIXTURE_TS) if c.chunk_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "greet"


def test_ts_class_name():
    classes = [c for c in chunk_file(FIXTURE_TS) if c.chunk_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Greeter"


def test_ts_method_parent_name():
    methods = [c for c in chunk_file(FIXTURE_TS) if c.chunk_type == "method"]
    assert len(methods) == 2
    assert all(m.parent_name == "Greeter" for m in methods)
    assert {m.name for m in methods} == {"constructor", "hello"}


def test_ts_start_line_less_than_end_line():
    for c in chunk_file(FIXTURE_TS):
        assert c.start_line < c.end_line, (
            f"{c.name}: start_line={c.start_line} >= end_line={c.end_line}"
        )


def test_ts_chunk_id_is_16_hex():
    for c in chunk_file(FIXTURE_TS):
        assert re.fullmatch(r"[0-9a-f]{16}", c.chunk_id), (
            f"{c.name}: invalid chunk_id={c.chunk_id!r}"
        )


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------

def test_java_chunk_count():
    chunks = chunk_file(FIXTURE_JAVA)
    # 1 class + 1 constructor (method) + 1 method
    assert len(chunks) == 3


def test_java_chunk_types():
    types = {c.chunk_type for c in chunk_file(FIXTURE_JAVA)}
    assert "class" in types
    assert "method" in types
    assert "function" not in types
    assert "module" not in types


def test_java_class_name():
    classes = [c for c in chunk_file(FIXTURE_JAVA) if c.chunk_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Sample"


def test_java_method_parent_name():
    methods = [c for c in chunk_file(FIXTURE_JAVA) if c.chunk_type == "method"]
    assert len(methods) == 2
    assert all(m.parent_name == "Sample" for m in methods)
    assert {m.name for m in methods} == {"Sample", "greet"}


def test_java_start_line_less_than_end_line():
    for c in chunk_file(FIXTURE_JAVA):
        assert c.start_line < c.end_line, (
            f"{c.name}: start_line={c.start_line} >= end_line={c.end_line}"
        )


def test_java_chunk_id_is_16_hex():
    for c in chunk_file(FIXTURE_JAVA):
        assert re.fullmatch(r"[0-9a-f]{16}", c.chunk_id), (
            f"{c.name}: invalid chunk_id={c.chunk_id!r}"
        )


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

def test_go_chunk_count():
    chunks = chunk_file(FIXTURE_GO)
    # 1 module (package+import) + 2 functions + 1 class (struct) + 1 method
    assert len(chunks) == 5


def test_go_chunk_types():
    types = {c.chunk_type for c in chunk_file(FIXTURE_GO)}
    assert types == {"module", "function", "class", "method"}


def test_go_function_names():
    funcs = [c for c in chunk_file(FIXTURE_GO) if c.chunk_type == "function"]
    assert len(funcs) == 2
    assert {f.name for f in funcs} == {"Hello", "Goodbye"}


def test_go_struct_name():
    classes = [c for c in chunk_file(FIXTURE_GO) if c.chunk_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Greeter"


def test_go_method_parent_name():
    methods = [c for c in chunk_file(FIXTURE_GO) if c.chunk_type == "method"]
    assert len(methods) == 1
    assert methods[0].name == "Greet"
    assert methods[0].parent_name == "Greeter"


def test_go_start_line_less_than_end_line():
    for c in chunk_file(FIXTURE_GO):
        assert c.start_line < c.end_line, (
            f"{c.name}: start_line={c.start_line} >= end_line={c.end_line}"
        )


def test_go_chunk_id_is_16_hex():
    for c in chunk_file(FIXTURE_GO):
        assert re.fullmatch(r"[0-9a-f]{16}", c.chunk_id), (
            f"{c.name}: invalid chunk_id={c.chunk_id!r}"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_file_returns_empty_list(tmp_path: Path):
    f = tmp_path / "empty.py"
    f.write_text("", encoding="utf-8")
    assert chunk_file(f) == []


def test_comments_only_python_returns_module_chunk(tmp_path: Path):
    f = tmp_path / "comments_only.py"
    f.write_text("# First comment\n# Second comment\n", encoding="utf-8")
    chunks = chunk_file(f)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "module"


def test_unsupported_extension_raises_parser_error():
    with pytest.raises(ParserError, match="Unsupported"):
        chunk_file(Path("foo.rb"))
