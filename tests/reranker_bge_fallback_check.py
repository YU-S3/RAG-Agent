from app.rag.retriever import HybridRetriever


class _NoScoreReranker:
    def __init__(self):
        self.last_meta = {"used": False, "reason": "mock_no_score", "latency_ms": 1}

    def score_pairs(self, query: str, docs: list[str], timeout_ms: int = 2000) -> list[float]:
        return []


def run() -> None:
    retriever = HybridRetriever(
        reranker_type="bge",
        bge_top_n=10,
        bge_timeout_ms=1000,
        bge_weight=0.5,
        reranker=_NoScoreReranker(),  # type: ignore[arg-type]
    )
    rows = [
        {"chunk_id": "c1", "text": "alpha beta", "embedding": [0.1, 0.2], "semantic_score_qdrant": 0.9},
        {"chunk_id": "c2", "text": "gamma delta", "embedding": [0.1, 0.2], "semantic_score_qdrant": 0.2},
    ]
    out = retriever.search(query="alpha", query_embedding=[0.1, 0.2], rows=rows, top_k=2)
    assert len(out) == 2
    assert retriever.last_search_meta.get("used_bge") is False
    assert all("final_score" in x for x in out)
    # no bge score => fallback to base score
    assert all(abs(float(x["final_score"]) - float(x["base_score"])) < 1e-9 for x in out)


if __name__ == "__main__":
    run()
