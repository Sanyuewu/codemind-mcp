from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from codemind.exceptions import ParserError
from codemind.indexing.parser import get_language, parse_file
from codemind.models import CodeChunk

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


def _chunk_id(file_path: str, start_line: int) -> str:
    return hashlib.sha256(f"{file_path}:{start_line}".encode()).hexdigest()[:16]


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _get_docstring(body_node: Node, source: bytes) -> str | None:
    if not body_node.named_children:
        return None
    first = body_node.named_children[0]
    if first.type != "expression_statement" or not first.named_children:
        return None
    inner = first.named_children[0]
    if inner.type in ("string", "concatenated_string"):
        return _node_text(source, inner)
    return None


def _get_signature(func_node: Node, source: bytes) -> str | None:
    body = func_node.child_by_field_name("body")
    if body is None:
        return None
    return source[func_node.start_byte:body.start_byte].decode("utf-8").rstrip().rstrip(":")


def _collect_leading_comments(outer_node: Node) -> list[Node]:
    comments: list[Node] = []
    expected_end_row = outer_node.start_point[0] - 1
    prev = outer_node.prev_named_sibling
    while prev is not None and prev.type == "comment":
        if prev.end_point[0] == expected_end_row:
            comments.insert(0, prev)
            expected_end_row = prev.start_point[0] - 1
            prev = prev.prev_named_sibling
        else:
            break
    return comments


def _unwrap_decorated(node: Node) -> Node | None:
    if node.type in ("function_definition", "class_definition"):
        return node
    if node.type == "decorated_definition":
        for child in node.named_children:
            if child.type in ("function_definition", "class_definition"):
                return child
    return None


def _extract_function_chunk(
    func_node: Node,
    outer_node: Node,
    leading: list[Node],
    source: bytes,
    file_path: str,
    language: str,
    chunk_type: str,
    parent_name: str | None,
) -> CodeChunk:
    name_node = func_node.child_by_field_name("name")
    name = _node_text(source, name_node) if name_node else "<unknown>"

    body = func_node.child_by_field_name("body")
    signature = _get_signature(func_node, source)
    docstring = _get_docstring(body, source) if body else None

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
    class_node: Node,
    outer_node: Node,
    leading: list[Node],
    source: bytes,
    file_path: str,
    language: str,
) -> list[CodeChunk]:
    name_node = class_node.child_by_field_name("name")
    class_name = _node_text(source, name_node) if name_node else "<unknown>"

    body = class_node.child_by_field_name("body")
    docstring = _get_docstring(body, source) if body else None

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
            inner = _unwrap_decorated(child)
            if inner and inner.type == "function_definition":
                method_leading = _collect_leading_comments(child)
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
                    )
                )

    return chunks


def chunk_file(path: Path) -> list[CodeChunk]:
    """Parse a Python file and return an AST-aware list of CodeChunks."""
    tree = parse_file(path)
    source = path.read_bytes()
    language = get_language(path)
    file_path = path.as_posix()

    claimed_comment_ids: set[int] = set()
    chunks: list[CodeChunk] = []

    for child in tree.root_node.named_children:
        actual = _unwrap_decorated(child)

        if actual is None:
            continue

        leading = _collect_leading_comments(child)
        claimed_comment_ids |= {n.id for n in leading}

        if actual.type == "function_definition":
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
                )
            )
        elif actual.type == "class_definition":
            chunks.extend(
                _extract_class_chunks(
                    class_node=actual,
                    outer_node=child,
                    leading=leading,
                    source=source,
                    file_path=file_path,
                    language=language,
                )
            )

    # Module chunk: top-level nodes that are not function/class and not claimed comments
    module_nodes = [
        c for c in tree.root_node.named_children
        if c.id not in claimed_comment_ids and _unwrap_decorated(c) is None
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
