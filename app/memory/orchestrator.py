import json
from typing import Any
from uuid import uuid4

from app.rag.embedder import HybridEmbedder
from app.rag.retriever import HybridRetriever
from app.rag.store import RagStore
from app.memory.session_store import SessionStore
from app.core.settings import get_settings


class MemoryOrchestrator:
    def __init__(self, embed_base_url: str, embed_model: str):
        settings = get_settings()
        self.session_store = SessionStore()
        self.rag_store = RagStore()
        self.embedder = HybridEmbedder(base_url=embed_base_url, model=embed_model)
        self.retriever = HybridRetriever(
            reranker_type=settings.rag_reranker_type,
            bge_model_name=settings.rag_bge_model_name,
            bge_device=settings.rag_bge_device,
            bge_backend=settings.rag_bge_backend,
            bge_onnx_provider=settings.rag_bge_onnx_provider,
            bge_top_n=settings.rag_bge_top_n,
            bge_timeout_ms=settings.rag_bge_timeout_ms,
            bge_weight=settings.rag_bge_weight,
        )
        self.vector_top_n = max(8, int(settings.rag_vector_candidate_top_n))
        self.vector_top_n_memory = max(8, int(settings.rag_vector_candidate_top_n_memory))

    @staticmethod
    def build_session_id(session_id: str | None, user_id: str | None) -> str:
        if session_id:
            return session_id
        if user_id:
            return f"user:{user_id}"
        return f"session:{uuid4().hex}"

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit]

    @staticmethod
    def _extract_summary(output: str) -> str:
        raw = output.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return str(parsed.get("summary", raw))
        except Exception:
            pass
        return raw

    async def retrieve(
        self,
        domain: str,
        query: str,
        session_id: str,
        user_id: str,
        top_k: int,
        use_memory: bool,
    ) -> dict[str, Any]:
        if not use_memory:
            return {
                "session_id": session_id,
                "memory_context": "",
                "rag_context": "",
                "memory_meta": {"enabled": False, "short_turns": 0, "rag_hits": 0, "long_hits": 0},
            }
        session_ctx = self.session_store.get_context(session_id)
        query_emb = await self.embedder.embed(query)
        doc_rows = self.rag_store.vector_search_chunks(
            domain=domain,
            query_embedding=query_emb,
            kind="doc",
            limit=max(top_k * 6, self.vector_top_n),
        )
        long_rows = self.rag_store.vector_search_chunks(
            domain=domain,
            query_embedding=query_emb,
            kind="memory",
            user_id=user_id,
            limit=max(top_k * 4, self.vector_top_n_memory),
        )
        doc_hits = self.retriever.search(query=query, query_embedding=query_emb, rows=doc_rows, top_k=top_k)
        doc_rerank_meta = dict(self.retriever.last_search_meta)
        long_hits = self.retriever.search(query=query, query_embedding=query_emb, rows=long_rows, top_k=top_k)
        long_rerank_meta = dict(self.retriever.last_search_meta)
        rag_lines = [f"[doc] {h.get('source','')} | {self._clip(str(h.get('text','')), 220)}" for h in doc_hits]
        long_lines = [f"[memory] {self._clip(str(h.get('text','')), 220)}" for h in long_hits]
        memory_context = self._clip(str(session_ctx["summary"]), 1000)
        if session_ctx["turns_text"]:
            memory_context = (memory_context + "\n" + self._clip(str(session_ctx["turns_text"]), 1200)).strip()
        rag_context = self._clip("\n".join(long_lines + rag_lines), 1800)
        return {
            "session_id": session_id,
            "memory_context": memory_context,
            "rag_context": rag_context,
            "memory_meta": {
                "enabled": True,
                "short_turns": len(session_ctx["turns"]),
                "rag_hits": len(doc_hits),
                "long_hits": len(long_hits),
                "doc_candidates": len(doc_rows),
                "long_candidates": len(long_rows),
                "reranker_type": self.retriever.reranker_type,
                "doc_rerank": doc_rerank_meta,
                "long_rerank": long_rerank_meta,
            },
        }

    async def persist(
        self,
        domain: str,
        session_id: str,
        user_id: str,
        task: str,
        output: str,
        use_memory: bool,
    ) -> None:
        if not use_memory:
            return
        self.session_store.append_turn(session_id=session_id, role="user", content=task)
        assistant_summary = self._extract_summary(output)
        self.session_store.append_turn(session_id=session_id, role="assistant", content=assistant_summary)
        text = f"用户问题: {self._clip(task, 300)}\n助手回答: {self._clip(assistant_summary, 400)}"
        emb = await self.embedder.embed(text)
        self.rag_store.upsert_chunks(
            domain=domain,
            chunks=[text],
            source="conversation",
            embeddings=[emb],
            kind="memory",
            user_id=user_id,
        )
