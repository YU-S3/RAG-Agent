import concurrent.futures
import time
from typing import Any


class BGEReranker:
    """BGE cross-encoder reranker with lazy-load and timeout guard."""

    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        backend: str = "onnxruntime",
        onnx_provider: str = "CPUExecutionProvider",
    ):
        self.model_name = model_name
        self.device = device
        self.backend = backend
        self.onnx_provider = onnx_provider
        self._model = None
        self._tokenizer = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._disabled = False
        self.last_meta: dict[str, Any] = {
            "enabled": False,
            "used": False,
            "reason": "not_initialized",
            "latency_ms": 0,
            "model_name": model_name,
            "backend": backend,
        }

    def _ensure_onnx_model(self) -> bool:
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer
        except Exception as exc:
            self.last_meta = {
                **self.last_meta,
                "enabled": False,
                "used": False,
                "reason": f"onnx_dependency_missing:{exc.__class__.__name__}",
            }
            return False
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = ORTModelForSequenceClassification.from_pretrained(
                self.model_name,
                export=True,
                provider=self.onnx_provider,
            )
            self.last_meta = {
                **self.last_meta,
                "enabled": True,
                "used": False,
                "reason": "ready",
                "backend": "onnxruntime",
            }
            return True
        except Exception as exc:
            self.last_meta = {
                **self.last_meta,
                "enabled": False,
                "used": False,
                "reason": f"onnx_model_load_failed:{exc.__class__.__name__}",
                "backend": "onnxruntime",
            }
            return False

    def _ensure_torch_model(self) -> bool:
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:
            self._disabled = True
            self.last_meta = {
                **self.last_meta,
                "enabled": False,
                "used": False,
                "reason": f"dependency_missing:{exc.__class__.__name__}",
                "backend": "torch",
            }
            return False
        try:
            self._model = CrossEncoder(self.model_name, device=self.device)
            self.last_meta = {
                **self.last_meta,
                "enabled": True,
                "used": False,
                "reason": "ready",
                "backend": "torch",
            }
            return True
        except Exception as exc:
            self._disabled = True
            self.last_meta = {
                **self.last_meta,
                "enabled": False,
                "used": False,
                "reason": f"model_load_failed:{exc.__class__.__name__}",
                "backend": "torch",
            }
            return False

    def _ensure_model(self) -> bool:
        if self._disabled:
            return False
        if self._model is not None:
            return True
        if self.backend == "onnxruntime":
            if self._ensure_onnx_model():
                return True
            # Fallback to torch backend when ONNX init failed.
            self.last_meta = {**self.last_meta, "reason": f"{self.last_meta.get('reason','')}:fallback_torch"}
            return self._ensure_torch_model()
        return self._ensure_torch_model()

    def _predict_pairs(self, query: str, docs: list[str]) -> list[float]:
        if self._model is None:
            return []
        if self.last_meta.get("backend") == "onnxruntime" and self._tokenizer is not None:
            inputs = self._tokenizer(
                [query] * len(docs),
                docs,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="np",
            )
            outputs = self._model(**inputs)
            logits = outputs.logits
            if hasattr(logits, "tolist"):
                logits = logits.tolist()
            scores: list[float] = []
            for row in logits:
                if isinstance(row, list):
                    scores.append(float(row[-1]))
                else:
                    scores.append(float(row))
            return scores
        pairs = [(query, doc) for doc in docs]
        raw = self._model.predict(pairs, show_progress_bar=False)
        return [float(x) for x in list(raw)]

    def score_pairs(self, query: str, docs: list[str], timeout_ms: int = 2000) -> list[float]:
        if not docs:
            self.last_meta = {
                **self.last_meta,
                "used": False,
                "reason": "no_docs",
                "latency_ms": 0,
            }
            return []
        if not self._ensure_model():
            return []
        started = time.perf_counter()
        timeout_sec = max(0.05, float(timeout_ms) / 1000.0)
        try:
            fut = self._pool.submit(self._predict_pairs, query, docs)
            scores = fut.result(timeout=timeout_sec)
            if len(scores) != len(docs):
                self.last_meta = {
                    **self.last_meta,
                    "used": False,
                    "reason": "score_length_mismatch",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
                return []
            self.last_meta = {
                **self.last_meta,
                "enabled": True,
                "used": True,
                "reason": "ok",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "docs": len(docs),
            }
            return scores
        except concurrent.futures.TimeoutError:
            try:
                fut.cancel()
            except Exception:
                pass
            self.last_meta = {
                **self.last_meta,
                "used": False,
                "reason": "timeout",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "docs": len(docs),
            }
            return []
        except Exception as exc:
            self.last_meta = {
                **self.last_meta,
                "used": False,
                "reason": f"predict_failed:{exc.__class__.__name__}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "docs": len(docs),
            }
            return []
