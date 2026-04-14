from app.rag.store import RagStore


class _FakeCollection:
    def __init__(self, name: str):
        self.name = name


class _FakeCollectionsResp:
    def __init__(self, names: list[str]):
        self.collections = [_FakeCollection(x) for x in names]


class _FakeHit:
    def __init__(self, payload: dict, score: float):
        self.payload = payload
        self.score = score
        self.id = payload.get("chunk_id", "id-1")


class _FakeQdrant:
    def __init__(self):
        self.search_calls: list[str] = []

    def get_collections(self):
        return _FakeCollectionsResp(["meta_agent_chunks_3", "meta_agent_chunks_256"])

    def search(self, *, collection_name, query_vector, query_filter, with_payload, with_vectors, limit):
        self.search_calls.append(collection_name)
        if collection_name.endswith("_3"):
            raise RuntimeError('Unexpected Response: 400 {"error":"Vector dimension error"}')
        return [
            _FakeHit(
                payload={
                    "chunk_id": "c-1",
                    "doc_id": "d-1",
                    "domain": "default",
                    "source": "manual",
                    "kind": "doc",
                    "user_id": "",
                    "text": "hello world",
                    "created_at": 1.0,
                },
                score=0.9,
            )
        ]


def run() -> None:
    store = RagStore()
    store.provider = "qdrant"
    fake = _FakeQdrant()
    store._qdrant = fake
    store._qdrant_collection_prefix = "meta_agent_chunks"
    store._qdrant_collection = "meta_agent_chunks_256"
    rows = store.vector_search_chunks(
        domain="default",
        query_embedding=[0.1] * 256,
        kind="doc",
        user_id="",
        limit=10,
    )
    assert rows, "rows should not be empty"
    assert all(name.endswith("_256") for name in fake.search_calls), f"unexpected searched collections: {fake.search_calls}"


if __name__ == "__main__":
    run()
