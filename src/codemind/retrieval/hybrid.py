from __future__ import annotations


def reciprocal_rank_fusion(
    bm25_results: list[tuple[str, float]],
    dense_results: list[tuple[str, float]],
    k: int,
) -> list[tuple[str, float]]:
    """RRF: score(d) = Σ 1/(k + rank), rank is 1-based. k must come from config.rrf_k."""
    scores: dict[str, float] = {}
    for rank, (chunk_id, _) in enumerate(bm25_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    for rank, (chunk_id, _) in enumerate(dense_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
