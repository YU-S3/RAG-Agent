import asyncio

from app.memory.orchestrator import MemoryOrchestrator


def run() -> None:
    orchestrator = MemoryOrchestrator(embed_base_url="http://127.0.0.1:11434", embed_model="nomic-embed-text")

    async def fake_embed(_text: str):
        return [0.1, 0.2, 0.3]

    def fake_vector_search_chunks(domain: str, query_embedding, kind=None, user_id="", limit=64):
        rows = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "domain": domain,
                "source": "manual",
                "kind": kind or "doc",
                "user_id": user_id,
                "text": "这是测试召回文本，包含关键术语。",
                "embedding": [0.1, 0.2, 0.3],
                "semantic_score_qdrant": 0.88,
                "created_at": 1.0,
            }
        ]
        return rows

    orchestrator.embedder.embed = fake_embed  # type: ignore[assignment]
    orchestrator.rag_store.vector_search_chunks = fake_vector_search_chunks  # type: ignore[assignment]

    result = asyncio.run(
        orchestrator.retrieve(
            domain="default",
            query="关键术语",
            session_id="s1",
            user_id="u1",
            top_k=3,
            use_memory=True,
        )
    )
    meta = result["memory_meta"]
    assert meta["enabled"] is True
    assert meta["rag_hits"] >= 1
    assert meta["doc_candidates"] >= 1


if __name__ == "__main__":
    run()
