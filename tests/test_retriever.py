"""
Unit tests for retriever module pure functions:
  - _is_locate_query: intent detection heuristic
  - _apply_source_boost: post-rerank score multiplier
"""
from __future__ import annotations

import pytest

from codemind.config import Settings
from codemind.models import CodeChunk, RetrievedChunk
from codemind.retrieval.retriever import _apply_source_boost, _is_locate_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(file_path: str, chunk_id: str = "abc123") -> CodeChunk:
    return CodeChunk(
        chunk_id=chunk_id,
        file_path=file_path,
        language="python",
        chunk_type="function",
        name="my_func",
        code="def my_func(): pass",
        start_line=1,
        end_line=1,
    )


def _make_result(file_path: str, score: float, chunk_id: str = "abc123") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=_make_chunk(file_path, chunk_id=chunk_id),
        score=score,
        retrieval_method="rerank",
    )


def _settings(boost: float = 1.5) -> Settings:
    return Settings(
        repo_path=".",
        source_boost_factor=boost,
        enable_reranker=False,
        enable_dense=False,
    )


# ---------------------------------------------------------------------------
# _is_locate_query
# ---------------------------------------------------------------------------

class TestIsLocateQuery:
    # --- positive cases (should detect as locate) ---

    @pytest.mark.parametrize("query", [
        "Where is the jsonable_encoder function?",
        "where is APIRoute defined?",
        "WHERE IS the FastAPI class?",          # case-insensitive
        "where are the helper functions?",
        "Is jsonable_encoder defined in encoders.py?",
        "How is get_dependant implemented?",
        "Can you find the definition of RRF?",
        "Show me the implementation of search",
        "I want to locate the OAuth2 class",
        "find the request_response function",
        "Find the exact definition",
        "在哪里定义了 APIRouter？",
        "这个函数定义在哪",
        "APIRoute 定义在哪个文件",
    ])
    def test_positive(self, query: str) -> None:
        assert _is_locate_query(query) is True, f"Expected locate match: {query!r}"

    # --- negative cases (should NOT be detected as locate) ---

    @pytest.mark.parametrize("query", [
        "How does FastAPI handle background tasks?",
        "Explain how OAuth2 authentication works",
        "What is the difference between APIRoute and APIWebSocketRoute?",
        "How do I use dependency injection in FastAPI?",
        "Compare OAuth2PasswordBearer and APIKeyHeader",
        "What does jsonable_encoder do with custom objects?",
        "Describe the RRF fusion algorithm",
        "How does the reranker improve results?",
    ])
    def test_negative(self, query: str) -> None:
        assert _is_locate_query(query) is False, f"Expected no locate match: {query!r}"

    def test_empty_string(self) -> None:
        assert _is_locate_query("") is False

    def test_partial_word_no_match(self) -> None:
        # "definitions" should not match "\bdefined\b" or "\bdefinition\b" because
        # word boundary prevents matching inside a longer word like "definitions"
        assert _is_locate_query("What are route definitions?") is False

    def test_case_insensitive(self) -> None:
        assert _is_locate_query("WHERE IS") is True
        assert _is_locate_query("IMPLEMENTED in module x") is True
        assert _is_locate_query("LOCATE the class") is True


# ---------------------------------------------------------------------------
# _apply_source_boost
# ---------------------------------------------------------------------------

class TestApplySourceBoost:
    def test_source_file_gets_boosted(self) -> None:
        result = _make_result("fastapi/routing.py", score=0.5, chunk_id="src1")
        boosted = _apply_source_boost([result], _settings(boost=1.5))
        assert len(boosted) == 1
        assert boosted[0].score == pytest.approx(0.75)  # 0.5 * 1.5

    def test_test_file_not_boosted(self) -> None:
        result = _make_result("tests/test_routing.py", score=0.5, chunk_id="tst1")
        boosted = _apply_source_boost([result], _settings(boost=1.5))
        assert boosted[0].score == pytest.approx(0.5)  # unchanged

    def test_docs_src_not_boosted(self) -> None:
        result = _make_result("docs_src/path_operation/tutorial001.py", score=0.5, chunk_id="doc1")
        boosted = _apply_source_boost([result], _settings(boost=1.5))
        assert boosted[0].score == pytest.approx(0.5)

    def test_examples_not_boosted(self) -> None:
        result = _make_result("examples/app.py", score=0.5, chunk_id="ex1")
        boosted = _apply_source_boost([result], _settings(boost=1.5))
        assert boosted[0].score == pytest.approx(0.5)

    def test_boost_factor_one_is_noop(self) -> None:
        results = [
            _make_result("fastapi/routing.py", score=0.8, chunk_id="s1"),
            _make_result("tests/test_routing.py", score=0.6, chunk_id="t1"),
        ]
        boosted = _apply_source_boost(results, _settings(boost=1.0))
        scores = [r.score for r in boosted]
        assert scores == pytest.approx([0.8, 0.6])

    def test_sorting_after_boost(self) -> None:
        # source file has lower raw score but gets boosted above test file
        src = _make_result("fastapi/routing.py", score=0.4, chunk_id="src1")
        tst = _make_result("tests/test_routing.py", score=0.5, chunk_id="tst1")
        boosted = _apply_source_boost([src, tst], _settings(boost=1.5))
        # src boosted to 0.6, test stays at 0.5 → src should be first
        assert boosted[0].chunk.file_path == "fastapi/routing.py"
        assert boosted[1].chunk.file_path == "tests/test_routing.py"
        assert boosted[0].score == pytest.approx(0.6)

    def test_retrieval_method_preserved(self) -> None:
        result = _make_result("fastapi/routing.py", score=0.5, chunk_id="src1")
        boosted = _apply_source_boost([result], _settings(boost=1.5))
        assert boosted[0].retrieval_method == "rerank"

    def test_empty_list(self) -> None:
        assert _apply_source_boost([], _settings()) == []
