import time

from app.rag.reranker import BGEReranker


class _SlowModel:
    def predict(self, _pairs, show_progress_bar=False):
        time.sleep(0.2)
        return [0.5]


def run() -> None:
    reranker = BGEReranker(model_name="mock", device="cpu")
    reranker._model = _SlowModel()  # type: ignore[attr-defined]
    reranker._disabled = False  # type: ignore[attr-defined]
    scores = reranker.score_pairs(query="q", docs=["d"], timeout_ms=50)
    assert scores == []
    assert reranker.last_meta.get("reason") == "timeout"


if __name__ == "__main__":
    run()
