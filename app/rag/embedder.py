import hashlib
from typing import Any

import httpx


class HybridEmbedder:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._resolved_endpoint: str | None = None
        self._remote_disabled = False

    @staticmethod
    def _hash_embedding(text: str, dim: int = 256) -> list[float]:
        out = [0.0] * dim
        for token in text.encode("utf-8"):
            idx = token % dim
            out[idx] += 1.0
        norm = sum(v * v for v in out) ** 0.5
        if norm == 0:
            return out
        return [v / norm for v in out]

    @staticmethod
    def _extract_embedding(data: Any) -> list[float]:
        if isinstance(data, dict):
            embedding = data.get("embedding")
            if isinstance(embedding, list) and embedding:
                return [float(x) for x in embedding]
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0]
                if isinstance(first, list) and first:
                    return [float(x) for x in first]
                if isinstance(first, dict):
                    vec = first.get("embedding")
                    if isinstance(vec, list) and vec:
                        return [float(x) for x in vec]
        return []

    @staticmethod
    def _payload_for(endpoint: str, model: str, text: str) -> dict[str, Any]:
        if endpoint == "/api/embed":
            return {"model": model, "input": text}
        return {"model": model, "prompt": text}

    async def embed(self, text: str) -> list[float]:
        if not self._remote_disabled:
            endpoints = [self._resolved_endpoint] if self._resolved_endpoint else ["/api/embed", "/api/embeddings"]
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    for endpoint in endpoints:
                        if endpoint is None:
                            continue
                        payload = self._payload_for(endpoint, self.model, text)
                        resp = await client.post(f"{self.base_url}{endpoint}", json=payload)
                        if resp.status_code == 404:
                            continue
                        resp.raise_for_status()
                        vec = self._extract_embedding(resp.json())
                        if vec:
                            self._resolved_endpoint = endpoint
                            return vec
            except Exception:
                pass
            if self._resolved_endpoint is None:
                self._remote_disabled = True
        salt = hashlib.md5(self.model.encode("utf-8")).hexdigest()[:8]
        return self._hash_embedding(f"{salt}:{text}")
