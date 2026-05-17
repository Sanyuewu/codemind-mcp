from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from codemind.exceptions import ParserError
from codemind.indexing.parser import get_language, parse_file
from codemind.models import CodeChunk

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


@dataclass(frozen=True)
class LanguageConfig:
    function_types: frozenset[str]
    class_types: frozenset[str]
    root_method_types: frozenset[str]   # top-level methods (Go only)
    method_types: frozenset[str]        # methods inside class body
    constructor_types: frozenset[str]   # constructors inside class body
    comment_types: frozenset[str]
    unwrap_fn: Callable[[object], object | None]
    class_name_fn: Callable[[object, bytes], str]
    has_docstrings: bool = False


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def _chunk_id(file_path: str, start_line: int) -> str:
    return hashlib.sha256(f"{file_path}:{start_line}".encode()).hexdigest()[:16]


def _node_text(source: bytes, node: "Node") -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _get_docstring(body_node: "Node", source: bytes) -> str | None:
    if not body_node.named_children:
        return None
    first = body_node.named_children[0]
    if first.type != "expression_statement" or not first.named_children:
        return None
    inner = first.named_children[0]
    if inner.type in ("string", "concatenated_string"):
        return _node_text(source, inner)
    return None


def _get_signature(func_node: "Node", source: bytes) -> str | None:
    body = func_node.child_by_field_name("body")
    if body is None:
        return None
    return source[func_node.start_byte:body.start_byte].decode("utf-8").rstrip().rstrip(":")


def _collect_leading_comments(
    outer_node: "Node",
    comment_types: frozenset[str],
) -> list["Node"]:
    comments: list[Node] = []
    expected_end_row = outer_node.start_point[0] - 1
    prev = outer_node.prev_named_sibling
    while prev is not None and prev.type in comment_types:
        if prev.end_point[0] == expected_end_row:
            comments.insert(0, prev)
            expected_end_row = prev.start_point[0] - 1
            prev = prev.prev_named_sibling
        else:
            break
    return comments


# ---------------------------------------------------------------------------
# Language-specific unwrap functions
# ---------------------------------------------------------------------------

def _unwrap_python(node: "Node") -> "Node | None":
    if node.type in ("function_definition", "class_definition"):
        return node
    if node.type == "decorated_definition":
        for child in node.named_children:
            if child.type in ("function_definition", "class_definition"):
                return child
    return None


def _unwrap_typescript(node: "Node") -> "Node | None":
    if node.type in ("function_declaration", "class_declaration", "method_definition"):
        return node
    if node.type == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl is not None and decl.type in ("function_declaration", "class_declaration"):
            return decl
    return None


def _unwrap_java(node: "Node") -> "Node | None":
    if node.type in ("class_declaration", "method_declaration", "constructor_declaration"):
        return node
    return None


def _unwrap_go(node: "Node") -> "Node | None":
    if node.type in ("function_declaration", "method_declaration", "type_declaration"):
        return node
    return None


# ---------------------------------------------------------------------------
# Class name extractors
# ---------------------------------------------------------------------------

def _get_class_name_default(node: "Node", source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    return _node_text(source, name_node) if name_node else "<unknown>"


def _get_go_type_name(node: "Node", source: bytes) -> str:
    # type_declaration → type_spec → name field (type_identifier)
    for child in node.named_children:
        if child.type == "type_spec":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                return _node_text(source, name_node)
    return "<unknown>"


# ---------------------------------------------------------------------------
# Go receiver extraction
# ---------------------------------------------------------------------------

def _get_go_receiver_type(method_node: "Node", source: bytes) -> str:
    receiver = method_node.child_by_field_name("receiver")
    if receiver is None:
        return "<unknown>"
    for child in receiver.named_children:
        if child.type == "parameter_declaration":
            type_node = child.child_by_field_name("type")
            if type_node is None:
                continue
            if type_node.type == "pointer_type":
                for grandchild in type_node.named_children:
                    if grandchild.type == "type_identifier":
                        return _node_text(source, grandchild)
            return _node_text(source, type_node)
    return "<unknown>"


# ---------------------------------------------------------------------------
# Chunk extractors
# ---------------------------------------------------------------------------

def _extract_function_chunk(
    func_node: "Node",
    outer_node: "Node",
    leading: "list[Node]",
    source: bytes,
    file_path: str,
    language: str,
    chunk_type: str,
    parent_name: str | None,
    config: LanguageConfig,
) -> CodeChunk:
    name_node = func_node.child_by_field_name("name")
    name = _node_text(source, name_node) if name_node else "<unknown>"

    body = func_node.child_by_field_name("body")
    signature = _get_signature(func_node, source)
    docstring = _get_docstring(body, source) if (body and config.has_docstrings) else None

    if leading:
        start_line = leading[0].start_point[0] + 1
        comment_text = "".join(
            source[c.start_byte:c.end_byte].decode("utf-8") + "\n" for c in leading
        )
        code = comment_text + _node_text(source, outer_node)
    else:
        start_line = outer_node.start_point[0] + 1
        code = _node_text(source, outer_node)

    end_line = outer_node.end_point[0] + 1

    return CodeChunk(
        chunk_id=_chunk_id(file_path, start_line),
        file_path=file_path,
        language=language,
        chunk_type=chunk_type,
        name=name,
        signature=signature,
        docstring=docstring,
        code=code,
        start_line=start_line,
        end_line=end_line,
        parent_name=parent_name,
    )


def _extract_class_chunks(
    class_node: "Node",
    outer_node: "Node",
    leading: "list[Node]",
    source: bytes,
    file_path: str,
    language: str,
    config: LanguageConfig,
) -> list[CodeChunk]:
    class_name = config.class_name_fn(class_node, source)

    body = class_node.child_by_field_name("body")
    docstring = _get_docstring(body, source) if (body and config.has_docstrings) else None

    if leading:
        start_line = leading[0].start_point[0] + 1
        comment_text = "".join(
            source[c.start_byte:c.end_byte].decode("utf-8") + "\n" for c in leading
        )
        code = comment_text + _node_text(source, outer_node)
    else:
        start_line = outer_node.start_point[0] + 1
        code = _node_text(source, outer_node)

    end_line = outer_node.end_point[0] + 1

    chunks: list[CodeChunk] = [
        CodeChunk(
            chunk_id=_chunk_id(file_path, start_line),
            file_path=file_path,
            language=language,
            chunk_type="class",
            name=class_name,
            signature=None,
            docstring=docstring,
            code=code,
            start_line=start_line,
            end_line=end_line,
            parent_name=None,
        )
    ]

    if body:
        for child in body.named_children:
            inner = config.unwrap_fn(child)
            if inner is None:
                continue
            if inner.type not in config.method_types and inner.type not in config.constructor_types:
                continue
            method_leading = _collect_leading_comments(child, config.comment_types)
            chunks.append(
                _extract_function_chunk(
                    func_node=inner,
                    outer_node=child,
                    leading=method_leading,
                    source=source,
                    file_path=file_path,
                    language=language,
                    chunk_type="method",
                    parent_name=class_name,
                    config=config,
                )
            )

    return chunks


# ---------------------------------------------------------------------------
# Language config registry
# ---------------------------------------------------------------------------

_LANGUAGE_CONFIGS: dict[str, LanguageConfig] = {
    "python": LanguageConfig(
        function_types=frozenset({"function_definition"}),
        class_types=frozenset({"class_definition"}),
        root_method_types=frozenset(),
        method_types=frozenset({"function_definition"}),
        constructor_types=frozenset(),
        comment_types=frozenset({"comment"}),
        unwrap_fn=_unwrap_python,
        class_name_fn=_get_class_name_default,
        has_docstrings=True,
    ),
    "typescript": LanguageConfig(
        function_types=frozenset({"function_declaration"}),
        class_types=frozenset({"class_declaration"}),
        root_method_types=frozenset(),
        method_types=frozenset({"method_definition"}),
        constructor_types=frozenset(),
        comment_types=frozenset({"comment"}),
        unwrap_fn=_unwrap_typescript,
        class_name_fn=_get_class_name_default,
        has_docstrings=False,
    ),
    "java": LanguageConfig(
        function_types=frozenset(),
        class_types=frozenset({"class_declaration"}),
        root_method_types=frozenset(),
        method_types=frozenset({"method_declaration"}),
        constructor_types=frozenset({"constructor_declaration"}),
        comment_types=frozenset({"line_comment", "block_comment"}),
        unwrap_fn=_unwrap_java,
        class_name_fn=_get_class_name_default,
        has_docstrings=False,
    ),
    "go": LanguageConfig(
        function_types=frozenset({"function_declaration"}),
        class_types=frozenset({"type_declaration"}),
        root_method_types=frozenset({"method_declaration"}),
        method_types=frozenset(),
        constructor_types=frozenset(),
        comment_types=frozenset({"comment"}),
        unwrap_fn=_unwrap_go,
        class_name_fn=_get_go_type_name,
        has_docstrings=False,
    ),
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chunk_file(path: Path) -> list[CodeChunk]:
    """Parse a source file and return an AST-aware list of CodeChunks."""
    tree = parse_file(path)
    source = path.read_bytes()
    language = get_language(path)
    file_path = path.as_posix()

    config = _LANGUAGE_CONFIGS.get(language)
    if config is None:
        raise ParserError(f"No chunker config for language: {language!r}")

    claimed_comment_ids: set[int] = set()
    chunks: list[CodeChunk] = []

    for child in tree.root_node.named_children:
        actual = config.unwrap_fn(child)

        if actual is None:
            continue

        leading = _collect_leading_comments(child, config.comment_types)
        claimed_comment_ids |= {n.id for n in leading}

        if actual.type in config.function_types:
            chunks.append(
                _extract_function_chunk(
                    func_node=actual,
                    outer_node=child,
                    leading=leading,
                    source=source,
                    file_path=file_path,
                    language=language,
                    chunk_type="function",
                    parent_name=None,
                    config=config,
                )
            )
        elif actual.type in config.class_types:
            chunks.extend(
                _extract_class_chunks(
                    class_node=actual,
                    outer_node=child,
                    leading=leading,
                    source=source,
                    file_path=file_path,
                    language=language,
                    config=config,
                )
            )
        elif actual.type in config.root_method_types:
            parent_name = _get_go_receiver_type(actual, source)
            chunks.append(
                _extract_function_chunk(
                    func_node=actual,
                    outer_node=child,
                    leading=leading,
                    source=source,
                    file_path=file_path,
                    language=language,
                    chunk_type="method",
                    parent_name=parent_name,
                    config=config,
                )
            )

    module_nodes = [
        c for c in tree.root_node.named_children
        if c.id not in claimed_comment_ids and config.unwrap_fn(c) is None
    ]

    if module_nodes:
        first, last = module_nodes[0], module_nodes[-1]
        start_line = first.start_point[0] + 1
        end_line = last.end_point[0] + 1
        code = source[first.start_byte:last.end_byte].decode("utf-8")
        chunks.append(
            CodeChunk(
                chunk_id=_chunk_id(file_path, start_line),
                file_path=file_path,
                language=language,
                chunk_type="module",
                name="<module>",
                signature=None,
                docstring=None,
                code=code,
                start_line=start_line,
                end_line=end_line,
                parent_name=None,
            )
        )

    return chunks
