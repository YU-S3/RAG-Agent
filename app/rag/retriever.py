from math import log
from typing import Any

from app.rag.reranker import BGEReranker
from app.rag.tokenize import tokenize


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        dot += a[i] * b[i]
        na += a[i] * a[i]
        nb += b[i] * b[i]
    if na == 0 or nb == 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def _bm25_scores(query: str, docs: list[str]) -> list[float]:
    if not docs:
        return []
    tokenized_docs = [tokenize(x) for x in docs]
    q_tokens = tokenize(query)
    avgdl = sum(len(d) for d in tokenized_docs) / max(1, len(tokenized_docs))
    df: dict[str, int] = {}
    for doc in tokenized_docs:
        for tok in set(doc):
            df[tok] = df.get(tok, 0) + 1
    scores: list[float] = []
    k1 = 1.5
    b = 0.75
    n_docs = len(tokenized_docs)
    for doc in tokenized_docs:
        tf: dict[str, int] = {}
        for tok in doc:
            tf[tok] = tf.get(tok, 0) + 1
        score = 0.0
        dl = len(doc)
        for tok in q_tokens:
            if tok not in tf:
                continue
            idf = log((n_docs - df.get(tok, 0) + 0.5) / (df.get(tok, 0) + 0.5) + 1)
            num = tf[tok] * (k1 + 1)
            den = tf[tok] + k1 * (1 - b + b * dl / max(1.0, avgdl))
            score += idf * num / den
        scores.append(score)
    return scores


class HybridRetriever:
    def __init__(
        self,
        reranker_type: str = "fusion",
        bge_model_name: str = "BAAI/bge-reranker-v2-m3",
        bge_device: str = "cpu",
        bge_backend: str = "onnxruntime",
        bge_onnx_provider: str = "CPUExecutionProvider",
        bge_top_n: int = 40,
        bge_timeout_ms: int = 2000,
        bge_weight: float = 0.5,
        reranker: BGEReranker | None = None,
    ):
        self.reranker_type = reranker_type
        self.bge_top_n = max(1, int(bge_top_n))
        self.bge_timeout_ms = max(100, int(bge_timeout_ms))
        self.bge_weight = max(0.0, min(1.0, float(bge_weight)))
        self.reranker = reranker or BGEReranker(
            model_name=bge_model_name,
            device=bge_device,
            backend=bge_backend,
            onnx_provider=bge_onnx_provider,
        )
        self.last_search_meta: dict[str, Any] = {}

    @staticmethod
    def _normalize_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        lo = min(scores)
        hi = max(scores)
        if hi <= lo:
            return [0.5 for _ in scores]
        return [(s - lo) / (hi - lo) for s in scores]

    def search(
        self,
        query: str,
        query_embedding: list[float],
        rows: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not rows:
            self.last_search_meta = {"reranker_type": self.reranker_type, "candidates": 0, "used_bge": False}
            return []
        docs = [str(r.get("text", "")) for r in rows]
        bm25 = _bm25_scores(query, docs)
        cos = [_cosine(query_embedding, r.get("embedding", [])) for r in rows]
        max_bm25 = max(bm25) if bm25 else 0.0
        q_tokens = set(tokenize(query))
        ranked: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            bm25_norm = 0.0 if max_bm25 <= 0 else bm25[idx] / max_bm25
            sem_qdrant = float(row.get("semantic_score_qdrant", 0.0))
            sem = max(0.0, sem_qdrant if sem_qdrant > 0 else cos[idx])
            fusion = 0.5 * bm25_norm + 0.5 * sem
            doc_tokens = set(tokenize(str(row.get("text", ""))))
            overlap = 0.0 if not q_tokens else len(q_tokens & doc_tokens) / len(q_tokens)
            base_score = 0.7 * fusion + 0.3 * overlap
            ranked.append(
                {
                    **row,
                    "bm25_score": bm25[idx],
                    "semantic_score": sem,
                    "fusion_score": fusion,
                    "overlap_score": overlap,
                    "base_score": base_score,
                    "bge_score": 0.0,
                    "final_score": base_score,
                    "rerank_score": base_score,
                }
            )
        ranked.sort(key=lambda x: x["base_score"], reverse=True)

        used_bge = False
        bge_latency_ms = 0
        if self.reranker_type in {"bge", "hybrid"}:
            candidates = ranked[: min(len(ranked), self.bge_top_n)]
            bge_raw = self.reranker.score_pairs(query=query, docs=[str(x.get("text", "")) for x in candidates], timeout_ms=self.bge_timeout_ms)
            bge_norm = self._normalize_scores(bge_raw)
            if bge_norm:
                used_bge = True
                for idx, item in enumerate(candidates):
                    item["bge_score"] = float(bge_norm[idx])
                    if self.reranker_type == "bge":
                        final_score = item["bge_score"]
                    else:
                        final_score = self.bge_weight * float(item["base_score"]) + (1.0 - self.bge_weight) * float(item["bge_score"])
                    item["final_score"] = final_score
                    item["rerank_score"] = final_score
            else:
                for item in candidates:
                    item["final_score"] = float(item["base_score"])
                    item["rerank_score"] = float(item["base_score"])
            bge_latency_ms = int(self.reranker.last_meta.get("latency_ms", 0))

        if self.reranker_type == "fusion":
            for item in ranked:
                item["final_score"] = float(item["base_score"])
                item["rerank_score"] = float(item["base_score"])

        ranked.sort(key=lambda x: x["final_score"], reverse=True)
        self.last_search_meta = {
            "reranker_type": self.reranker_type,
            "candidates": len(rows),
            "bge_top_n": min(len(rows), self.bge_top_n),
            "used_bge": used_bge,
            "bge_weight": self.bge_weight,
            "bge_latency_ms": bge_latency_ms,
            "bge_meta": dict(self.reranker.last_meta),
            "top_final_score": float(ranked[0]["final_score"]) if ranked else 0.0,
        }
        return ranked[:top_k]
