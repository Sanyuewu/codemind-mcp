from __future__ import annotations

import warnings
from pathlib import Path

from tree_sitter import Tree
from tree_sitter_languages import get_parser as _get_ts_parser

from codemind.exceptions import ParserError

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
}


def get_language(path: Path) -> str:
    """Return the tree-sitter language name for a file path.

    Raises ParserError for unsupported extensions.
    """
    suffix = path.suffix.lower()
    if suffix not in _EXTENSION_TO_LANGUAGE:
        raise ParserError(
            f"Unsupported file extension: {suffix!r} (path: {path})"
        )
    return _EXTENSION_TO_LANGUAGE[suffix]


def parse_file(path: Path) -> Tree:
    """Parse a source file and return its tree-sitter AST Tree.

    Raises ParserError on unsupported language, read failure, or parse failure.
    """
    language = get_language(path)

    try:
        source = path.read_bytes()
    except OSError as e:
        raise ParserError(f"Cannot read file {path}: {e}") from e

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            parser = _get_ts_parser(language)
        tree = parser.parse(source)
    except Exception as e:
        raise ParserError(f"tree-sitter failed to parse {path}: {e}") from e

    if tree.root_node is None:
        raise ParserError(f"Parser returned empty AST for {path}")

    if tree.root_node.has_error:
        raise ParserError(f"Syntax errors detected in {path}")

    return tree
