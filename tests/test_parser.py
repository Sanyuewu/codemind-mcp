import pytest
from pathlib import Path

from codemind.indexing.parser import get_language, parse_file
from codemind.exceptions import ParserError

FIXTURE = Path(__file__).parent / "fixtures" / "mini_repo" / "sample.py"


def test_parse_python_succeeds():
    tree = parse_file(FIXTURE)
    assert tree.root_node.type == "module"


def test_root_node_has_children():
    tree = parse_file(FIXTURE)
    top_level_types = {n.type for n in tree.root_node.children}
    assert "function_definition" in top_level_types
    assert "class_definition" in top_level_types


def test_get_language_python():
    assert get_language(Path("foo.py")) == "python"


def test_unsupported_ext_raises():
    with pytest.raises(ParserError, match="Unsupported"):
        get_language(Path("foo.xyz"))


def test_parse_unsupported_ext_raises():
    with pytest.raises(ParserError, match="Unsupported"):
        parse_file(Path("foo.xyz"))


def test_parse_broken_python_warns_not_raises(tmp_path: Path):
    # Day 11 fix: tree-sitter 1.10.2 has_error on Annotated[...,] syntax is
    # downgraded from ParserError to a warning so broken files still return a tree.
    broken = tmp_path / "broken.py"
    broken.write_text("def foo(\n  # unclosed paren\nclass Bar:\n    pass", encoding="utf-8")
    tree = parse_file(broken)
    assert tree.root_node.has_error
