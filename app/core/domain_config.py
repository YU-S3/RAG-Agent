from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.settings import get_settings


class RetryPolicy(BaseModel):
    """重试控制策略。"""

    max_retries: int = 2
    confidence_threshold: float = 0.85


class LocalModelPolicy(BaseModel):
    """本地模型调用配置。"""

    provider: str = "ollama"
    model: str = "qwen3:8b"
    base_url: str = "http://127.0.0.1:11434"
    fallback_models: list[str] = Field(default_factory=list)
    lite_model: str | None = None
    budget_tokens: int = 4096


class DomainConfig(BaseModel):
    """领域级配置定义。"""

    domain: str
    version: str = "1.0"
    model_policy: LocalModelPolicy = Field(default_factory=LocalModelPolicy)
    tools: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


def load_domain_config(domain: str) -> DomainConfig:
    """读取并校验领域配置文件。"""

    settings = get_settings()
    file_path = settings.domain_root_path / domain / "domain.yaml"
    if not file_path.exists():
        raise FileNotFoundError(f"Domain config not found: {file_path}")
    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    return DomainConfig.model_validate(data)
