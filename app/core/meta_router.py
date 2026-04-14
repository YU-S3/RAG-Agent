from typing import Any

from pydantic import BaseModel

from app.core.domain_config import DomainConfig, load_domain_config


class RuntimeContext(BaseModel):
    """运行工作流所需的统一上下文。"""

    domain: str
    task: str
    session_id: str
    user_id: str
    use_memory: bool
    top_k: int
    domain_config: DomainConfig
    output_format: dict[str, Any]


class MetaRouter:
    """根据请求信息解析领域配置。"""

    def __init__(self, default_domain: str = "default"):
        self.default_domain = default_domain

    def resolve(
        self,
        domain: str | None,
        task: str,
        session_id: str,
        user_id: str,
        use_memory: bool,
        top_k: int,
    ) -> RuntimeContext:
        """将输入请求映射为可执行上下文。"""

        resolved_domain = domain or self.default_domain
        cfg = load_domain_config(resolved_domain)
        return RuntimeContext(
            domain=resolved_domain,
            task=task,
            session_id=session_id,
            user_id=user_id,
            use_memory=use_memory,
            top_k=top_k,
            domain_config=cfg,
            output_format=cfg.output_schema,
        )
