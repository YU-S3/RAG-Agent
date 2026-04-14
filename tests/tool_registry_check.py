from app.workflow.tools import ToolRegistry


def run() -> None:
    """验证工具注册、参数校验与权限控制。"""

    registry = ToolRegistry()
    ok = registry.run(
        domain="default",
        name="mock_search",
        args={"task": "测试任务", "plan": "计划"},
        allowed_permissions={"readonly"},
    )
    assert "error" not in ok
    invalid = registry.run(
        domain="default",
        name="mock_search",
        args={"task": 123},
        allowed_permissions={"readonly"},
    )
    assert "invalid_arg_type" in invalid.get("error", "")
    denied = registry.run(
        domain="default",
        name="mock_search",
        args={"task": "测试任务"},
        allowed_permissions={"write"},
    )
    assert "permission_denied" in denied.get("error", "")


if __name__ == "__main__":
    run()
