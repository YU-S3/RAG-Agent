from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用运行时配置。"""

    app_name: str = "Meta Agent"
    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    llm_cache_ttl_seconds: int = 600
    llm_default_budget_tokens: int = 4096
    remote_llm_enabled: bool = True
    remote_llm_provider: str = "openai_compatible"
    remote_llm_base_url: str = ""
    remote_llm_api_key: str = ""
    remote_llm_model: str = ""
    remote_llm_timeout_seconds: int = 180
    security_enabled: bool = False
    auth_bearer_token: str = "change-me"
    input_block_patterns: str = "rm -rf|drop table|shutdown|格式化磁盘"
    rate_limit_per_minute: int = 120
    release_canary_percent: int = 0
    rollback_enabled: bool = False
    rag_embedding_model: str = "nomic-embed-text"
    rag_top_k: int = 4
    rag_chunk_size: int = 400
    rag_chunk_overlap: int = 80
    rag_chunk_min_size: int = 80
    rag_chunk_strategy: str = "spacy_auto"
    rag_spacy_model_zh: str = "zh_core_web_sm"
    rag_spacy_model_en: str = "en_core_web_sm"
    rag_vector_candidate_top_n: int = 64
    rag_vector_candidate_top_n_memory: int = 32
    rag_reranker_type: str = "hybrid"
    rag_bge_model_name: str = "BAAI/bge-reranker-v2-m3"
    rag_bge_device: str = "cpu"
    rag_bge_backend: str = "onnxruntime"
    rag_bge_onnx_provider: str = "CPUExecutionProvider"
    rag_bge_top_n: int = 40
    rag_bge_timeout_ms: int = 30000
    rag_bge_weight: float = 0.5
    rag_store_provider: str = "auto"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "meta_agent_chunks"
    qdrant_timeout_seconds: int = 6
    memory_session_ttl_seconds: int = 86400
    memory_window_size: int = 8
    debug_local_enabled: bool = True
    domain_config_root: str = Field(default="domains")
    prompt_root: str = Field(default="prompts")
    tools_root: str = Field(default="tools")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def domain_root_path(self) -> Path:
        return self.project_root / self.domain_config_root

    @property
    def prompt_root_path(self) -> Path:
        return self.project_root / self.prompt_root

    @property
    def tools_root_path(self) -> Path:
        return self.project_root / self.tools_root


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回缓存后的配置实例。"""

    return Settings()
