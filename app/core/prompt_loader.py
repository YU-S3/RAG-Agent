from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.settings import get_settings


def render_prompt(domain: str, template_name: str, context: dict[str, Any]) -> str:
    """按领域渲染模板提示词。"""

    settings = get_settings()
    domain_prompt_dir = settings.prompt_root_path / domain
    env = Environment(
        loader=FileSystemLoader(str(domain_prompt_dir)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    template = env.get_template(template_name)
    return template.render(**context)
