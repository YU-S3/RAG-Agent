from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field

from app.core.settings import get_settings


def mock_search(args: dict[str, Any]) -> dict[str, Any]:
    """模拟检索工具。"""

    task = str(args.get("task", ""))
    keywords = [part for part in task.replace("，", " ").replace(",", " ").split() if part]
    return {"tool": "mock_search", "keywords": keywords[:5], "hits": len(keywords)}


def mock_calculator(args: dict[str, Any]) -> dict[str, Any]:
    """模拟统计工具。"""

    task = str(args.get("task", ""))
    text_length = len(task)
    token_estimate = max(1, text_length // 2)
    return {"tool": "mock_calculator", "text_length": text_length, "token_estimate": token_estimate}


class ToolSpec(BaseModel):
    """工具协议定义。"""

    name: str
    impl: str
    permission: str = "readonly"
    args_schema: dict[str, Any] = Field(default_factory=dict)


class ToolRegistry:
    """支持扫描注册、参数校验与权限控制的工具中心。"""

    def __init__(self):
        self._impl_map: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "mock_search": mock_search,
            "mock_calculator": mock_calculator,
        }
        self._domain_specs: dict[str, dict[str, ToolSpec]] = {}
        self._loaded_domains: set[str] = set()

    def _domain_dir(self, domain: str) -> Path:
        settings = get_settings()
        return settings.tools_root_path / domain

    def _scan_and_register(self, domain: str) -> None:
        if domain in self._loaded_domains:
            return
        specs: dict[str, ToolSpec] = {}
        domain_dir = self._domain_dir(domain)
        if not domain_dir.exists():
            self._domain_specs[domain] = specs
            self._loaded_domains.add(domain)
            return
        for file_path in sorted(domain_dir.glob("*.yaml")):
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
            spec = ToolSpec.model_validate(raw)
            specs[spec.name] = spec
        self._domain_specs[domain] = specs
        self._loaded_domains.add(domain)

    @staticmethod
    def _validate_type(value: Any, expected_type: str) -> bool:
        type_map: dict[str, type] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        return isinstance(value, expected)

    def _validate_args(self, spec: ToolSpec, args: dict[str, Any]) -> str | None:
        schema = spec.args_schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for key in required:
            if key not in args:
                return f"missing_required_arg:{key}"
        for key, value in args.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type and not self._validate_type(value, expected_type):
                    return f"invalid_arg_type:{key}:{expected_type}"
        return None

    def run(
        self,
        domain: str,
        name: str,
        args: dict[str, Any],
        allowed_permissions: set[str] | None = None,
    ) -> dict[str, Any]:
        """执行指定领域工具并执行参数与权限检查。"""

        self._scan_and_register(domain)
        spec = self._domain_specs.get(domain, {}).get(name)
        if spec is None:
            return {"tool": name, "error": f"tool_not_registered:{name}"}
        effective_permissions = allowed_permissions or {"readonly"}
        if spec.permission not in effective_permissions:
            return {"tool": name, "error": f"permission_denied:{spec.permission}"}
        validation_error = self._validate_args(spec, args)
        if validation_error:
            return {"tool": name, "error": validation_error}
        impl = self._impl_map.get(spec.impl)
        if impl is None:
            return {"tool": name, "error": f"impl_not_found:{spec.impl}"}
        try:
            result = impl(args)
            return {"tool": name, "permission": spec.permission, "data": result}
        except Exception as exc:
            return {"tool": name, "error": str(exc)}
