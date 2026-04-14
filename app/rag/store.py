import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class RagStore:
    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.file_path = settings.project_root / "eval" / "rag" / "chunks.jsonl"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider = "local"
        self._qdrant = None
        self._qdrant_collection_prefix = settings.qdrant_collection
        self._qdrant_collection = settings.qdrant_collection
        self._try_enable_qdrant()

    def _read_qdrant_credentials(self) -> tuple[str, str]:
        url = self.settings.qdrant_url.strip()
        key = self.settings.qdrant_api_key.strip()
        return url, key

    def _try_enable_qdrant(self) -> None:
        if self.settings.rag_store_provider == "local":
            return
        url, key = self._read_qdrant_credentials()
        if not url:
            if self.settings.rag_store_provider == "qdrant":
                logger.warning("qdrant url missing, fallback to local store")
            return
        try:
            from qdrant_client import QdrantClient
        except Exception as exc:
            logger.warning("qdrant client not available, fallback to local store: %s", exc)
            return
        try:
            timeout = max(2.0, float(self.settings.qdrant_timeout_seconds))
            self._qdrant = QdrantClient(url=url, api_key=key or None, timeout=timeout)
            # Eagerly verify connection and credentials to avoid false-positive provider switch.
            self._qdrant.get_collections()
            self.provider = "qdrant"
            logger.info("rag store provider switched to qdrant")
        except Exception as exc:
            logger.warning("qdrant init failed, fallback to local store: %s", exc)

    def _collection_for_size(self, vector_size: int) -> str:
        return f"{self._qdrant_collection_prefix}_{vector_size}"

    @staticmethod
    def _safe_collection_token(raw: str) -> str:
        token = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip().lower())
        token = token.strip("_")
        return token or "unknown"

    def _doc_collection_name(self, domain: str, source: str, vector_size: int) -> str:
        source_tail = source.split(":")[-1].strip() if source else ""
        base = Path(source_tail or source or "document").name or "document"
        stem = Path(base).stem or base
        safe_domain = self._safe_collection_token(domain)
        safe_stem = self._safe_collection_token(stem)
        name = f"{self._qdrant_collection_prefix}__{safe_domain}__doc__{safe_stem}__{vector_size}"
        if len(name) > 180:
            name = name[:160].rstrip("_")
        return name

    def _is_doc_collection(self, collection_name: str, domain: str) -> bool:
        safe_domain = self._safe_collection_token(domain)
        prefix = f"{self._qdrant_collection_prefix}__{safe_domain}__doc__"
        return collection_name.startswith(prefix)

    def _extract_doc_name_from_collection(self, collection_name: str) -> str:
        parts = collection_name.split("__")
        if len(parts) < 5:
            return collection_name
        return parts[-2] or collection_name

    def _ensure_qdrant_collection(self, collection_name: str, vector_size: int) -> None:
        if self._qdrant is None:
            return
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        exists = self._qdrant.collection_exists(collection_name)
        if not exists:
            self._qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        for key in ("domain", "kind", "user_id", "doc_id"):
            try:
                self._qdrant.create_payload_index(
                    collection_name=collection_name,
                    field_name=key,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            except Exception:
                continue

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.file_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            row = line.strip()
            if not row:
                continue
            out.append(json.loads(row))
        return out

    def _append_many(self, items: list[dict[str, Any]]) -> None:
        with self.file_path.open("a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _upsert_qdrant(
        self,
        domain: str,
        chunks: list[str],
        source: str,
        embeddings: list[list[float]],
        resolved_doc_id: str,
        kind: str,
        user_id: str,
    ) -> dict[str, Any]:
        if self._qdrant is None:
            raise RuntimeError("qdrant_not_ready")
        from qdrant_client.models import PointStruct

        vector_size = len(embeddings[0]) if embeddings else 0
        if vector_size <= 0:
            return {"doc_id": resolved_doc_id, "chunks": 0}
        if kind == "doc":
            collection_name = self._doc_collection_name(domain=domain, source=source, vector_size=vector_size)
        else:
            collection_name = self._collection_for_size(vector_size)
        self._qdrant_collection = collection_name
        self._ensure_qdrant_collection(collection_name=collection_name, vector_size=vector_size)
        now = time.time()
        points: list[PointStruct] = []
        for idx, chunk in enumerate(chunks):
            points.append(
                PointStruct(
                    id=uuid4().hex,
                    vector=embeddings[idx],
                    payload={
                        "chunk_id": uuid4().hex,
                        "doc_id": resolved_doc_id,
                        "domain": domain,
                        "source": source,
                        "kind": kind,
                        "user_id": user_id,
                        "text": chunk,
                        "created_at": now,
                    },
                )
            )
        self._qdrant.upsert(collection_name=collection_name, points=points, wait=True)
        return {"doc_id": resolved_doc_id, "chunks": len(points)}

    def _list_qdrant(
        self,
        domain: str,
        kind: str | None = None,
        user_id: str = "",
        include_embeddings: bool = True,
    ) -> list[dict[str, Any]]:
        if self._qdrant is None:
            return []
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            collections = self._qdrant.get_collections().collections
            names = [c.name for c in collections if c.name == self._qdrant_collection_prefix or c.name.startswith(f"{self._qdrant_collection_prefix}_") or self._is_doc_collection(c.name, domain)]
            if not names:
                names = [self._qdrant_collection]
            if kind == "doc":
                names = [name for name in names if self._is_doc_collection(name, domain)]
            elif kind == "memory":
                names = [name for name in names if name == self._qdrant_collection_prefix or name.startswith(f"{self._qdrant_collection_prefix}_")]
            if not names:
                return []
            must = [FieldCondition(key="domain", match=MatchValue(value=domain))]
            if kind:
                must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))
            if user_id:
                rows: list[dict[str, Any]] = []
                for name in names:
                    for uid in ("", user_id):
                        current_must = list(must)
                        current_must.append(FieldCondition(key="user_id", match=MatchValue(value=uid)))
                        points, _ = self._qdrant.scroll(
                            collection_name=name,
                            scroll_filter=Filter(must=current_must),
                            with_vectors=include_embeddings,
                            with_payload=True if include_embeddings else ["chunk_id", "doc_id", "domain", "source", "kind", "user_id", "text", "created_at"],
                            limit=2000,
                        )
                        for p in points:
                            payload = dict(p.payload or {})
                            if include_embeddings:
                                payload["embedding"] = list(p.vector or [])
                            rows.append(payload)
                return rows
            out: list[dict[str, Any]] = []
            for name in names:
                points, _ = self._qdrant.scroll(
                    collection_name=name,
                    scroll_filter=Filter(must=must),
                    with_vectors=include_embeddings,
                    with_payload=True if include_embeddings else ["chunk_id", "doc_id", "domain", "source", "kind", "user_id", "text", "created_at"],
                    limit=4000,
                )
                for p in points:
                    payload = dict(p.payload or {})
                    if include_embeddings:
                        payload["embedding"] = list(p.vector or [])
                    out.append(payload)
            return out
        except Exception as exc:
            logger.warning("qdrant list failed, fallback local: %s", exc)
            return []

    def _vector_search_qdrant(
        self,
        domain: str,
        query_embedding: list[float],
        kind: str | None = None,
        user_id: str = "",
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        if self._qdrant is None or not query_embedding:
            return []
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            collections = self._qdrant.get_collections().collections
            names = [c.name for c in collections if c.name == self._qdrant_collection_prefix or c.name.startswith(f"{self._qdrant_collection_prefix}_") or self._is_doc_collection(c.name, domain)]
            query_dim = len(query_embedding)
            preferred = self._collection_for_size(query_dim)
            # Production rule: query only collections whose vector dimension matches the query embedding.
            if kind == "doc":
                suffix = f"__{query_dim}"
                names = [name for name in names if self._is_doc_collection(name, domain) and name.endswith(suffix)]
            elif preferred in names:
                names = [preferred]
            else:
                suffix = f"_{query_dim}"
                same_dim = [name for name in names if name.endswith(suffix)]
                if same_dim:
                    names = same_dim
                elif self._qdrant_collection in names:
                    names = [self._qdrant_collection]
                elif not names:
                    names = [self._qdrant_collection]

            def _run_search(collection_name: str, flt: Filter) -> list[Any]:
                # Compatible with multiple qdrant-client versions.
                if hasattr(self._qdrant, "search"):
                    return self._qdrant.search(
                        collection_name=collection_name,
                        query_vector=query_embedding,
                        query_filter=flt,
                        with_payload=True,
                        with_vectors=False,
                        limit=limit,
                    )
                if hasattr(self._qdrant, "query_points"):
                    resp = self._qdrant.query_points(
                        collection_name=collection_name,
                        query=query_embedding,
                        query_filter=flt,
                        with_payload=True,
                        with_vectors=False,
                        limit=limit,
                    )
                    points = getattr(resp, "points", None)
                    return list(points or [])
                return []

            base_must = [FieldCondition(key="domain", match=MatchValue(value=domain))]
            if kind:
                base_must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))

            results: dict[str, dict[str, Any]] = {}
            for name in names:
                filters: list[Filter] = []
                if user_id:
                    filters.append(Filter(must=base_must + [FieldCondition(key="user_id", match=MatchValue(value=""))]))
                    filters.append(Filter(must=base_must + [FieldCondition(key="user_id", match=MatchValue(value=user_id))]))
                else:
                    filters.append(Filter(must=base_must))
                for flt in filters:
                    try:
                        hits = _run_search(name, flt)
                    except Exception as inner_exc:
                        # Skip mismatched-dimension collections instead of failing the whole request.
                        if "Vector dimension error" in str(inner_exc):
                            logger.warning("qdrant vector search skip collection=%s due_to_dimension_mismatch", name)
                            continue
                        logger.warning("qdrant vector search failed in collection=%s err=%s", name, inner_exc)
                        continue
                    for hit in hits:
                        payload = dict(getattr(hit, "payload", None) or {})
                        chunk_id = str(payload.get("chunk_id") or getattr(hit, "id", ""))
                        if not chunk_id:
                            continue
                        row = {**payload, "semantic_score_qdrant": float(getattr(hit, "score", 0.0))}
                        prev = results.get(chunk_id)
                        if prev is None or float(row["semantic_score_qdrant"]) > float(prev.get("semantic_score_qdrant", 0.0)):
                            results[chunk_id] = row
            rows = list(results.values())
            rows.sort(key=lambda x: float(x.get("semantic_score_qdrant", 0.0)), reverse=True)
            return rows[:limit]
        except Exception as exc:
            logger.warning("qdrant vector search failed, fallback local: %s", exc)
            return []

    def list_document_collections(self, domain: str) -> list[dict[str, Any]]:
        if self.provider == "qdrant" and self._qdrant is not None:
            try:
                collections = self._qdrant.get_collections().collections
                names = [c.name for c in collections if self._is_doc_collection(c.name, domain)]
                names.sort(reverse=True)
                return [
                    {
                        "doc_id": name,
                        "source": self._extract_doc_name_from_collection(name),
                        "chunks": 0,
                        "created_at": 0.0,
                        "updated_at": 0.0,
                    }
                    for name in names
                ]
            except Exception as exc:
                logger.warning("qdrant list collections failed, fallback local: %s", exc)
        rows = self.list_chunks(domain=domain, kind="doc", include_embeddings=False)
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            doc_id = str(row.get("doc_id") or row.get("chunk_id") or "unknown")
            item = grouped.get(doc_id)
            if item is None:
                grouped[doc_id] = {
                    "doc_id": doc_id,
                    "source": str(row.get("source") or "unknown"),
                    "chunks": 1,
                    "created_at": float(row.get("created_at") or 0.0),
                    "updated_at": float(row.get("created_at") or 0.0),
                }
                continue
            item["chunks"] += 1
            ts = float(row.get("created_at") or 0.0)
            item["created_at"] = min(float(item["created_at"]), ts)
            item["updated_at"] = max(float(item["updated_at"]), ts)
        return list(grouped.values())

    def upsert_chunks(
        self,
        domain: str,
        chunks: list[str],
        source: str,
        embeddings: list[list[float]],
        doc_id: str | None = None,
        kind: str = "doc",
        user_id: str = "",
    ) -> dict[str, Any]:
        resolved_doc_id = doc_id or uuid4().hex
        if self.provider == "qdrant":
            try:
                return self._upsert_qdrant(
                    domain=domain,
                    chunks=chunks,
                    source=source,
                    embeddings=embeddings,
                    resolved_doc_id=resolved_doc_id,
                    kind=kind,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning("qdrant upsert failed, fallback local: %s", exc)
        now = time.time()
        rows: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            rows.append(
                {
                    "chunk_id": uuid4().hex,
                    "doc_id": resolved_doc_id,
                    "domain": domain,
                    "source": source,
                    "kind": kind,
                    "user_id": user_id,
                    "text": chunk,
                    "embedding": embeddings[idx],
                    "created_at": now,
                }
            )
        self._append_many(rows)
        return {"doc_id": resolved_doc_id, "chunks": len(rows)}

    def list_chunks(
        self,
        domain: str,
        kind: str | None = None,
        user_id: str = "",
        include_embeddings: bool = True,
    ) -> list[dict[str, Any]]:
        if self.provider == "qdrant":
            rows = self._list_qdrant(
                domain=domain,
                kind=kind,
                user_id=user_id,
                include_embeddings=include_embeddings,
            )
            if rows:
                return rows
        all_rows = self._read_all()
        out: list[dict[str, Any]] = []
        for row in all_rows:
            if row.get("domain") != domain:
                continue
            if kind and row.get("kind") != kind:
                continue
            if user_id and row.get("user_id") not in ("", user_id):
                continue
            out.append(row)
        return out

    def vector_search_chunks(
        self,
        domain: str,
        query_embedding: list[float],
        kind: str | None = None,
        user_id: str = "",
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        if self.provider == "qdrant":
            rows = self._vector_search_qdrant(
                domain=domain,
                query_embedding=query_embedding,
                kind=kind,
                user_id=user_id,
                limit=limit,
            )
            if rows:
                return rows
        rows = self.list_chunks(domain=domain, kind=kind, user_id=user_id, include_embeddings=True)
        return rows[:limit]
