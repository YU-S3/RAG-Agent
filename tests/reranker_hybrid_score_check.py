from app.rag.retriever import HybridRetriever


class _FixedScoreReranker:
    def __init__(self, scores: list[float]):
        self.scores = scores
        self.last_meta = {"used": True, "reason": "ok", "latency_ms": 2}

    def score_pairs(self, query: str, docs: list[str], timeout_ms: int = 2000) -> list[float]:
        return list(self.scores[: len(docs)])


def run() -> None:
    reranker = _FixedScoreReranker([0.1, 0.9, 0.2])
    retriever = HybridRetriever(
        reranker_type="hybrid",
        bge_top_n=3,
        bge_timeout_ms=1000,
        bge_weight=0.0,
        reranker=reranker,  # type: ignore[arg-type]
    )
    rows = [
        {"chunk_id": "c1", "text": "foo bar", "embedding": [0.1, 0.1], "semantic_score_qdrant": 0.4},
        {"chunk_id": "c2", "text": "foo baz", "embedding": [0.1, 0.1], "semantic_score_qdrant": 0.5},
        {"chunk_id": "c3", "text": "foo qux", "embedding": [0.1, 0.1], "semantic_score_qdrant": 0.3},
    ]
    out = retriever.search(query="foo", query_embedding=[0.1, 0.1], rows=rows, top_k=3)
    assert len(out) == 3
    assert retriever.last_search_meta.get("used_bge") is True
    assert all("bge_score" in x and "final_score" in x and "base_score" in x for x in out)
    # bge should affect at least one ranking score in hybrid mode.
    assert any(abs(float(x["final_score"]) - float(x["base_score"])) > 1e-9 for x in out)


if __name__ == "__main__":
    run()
