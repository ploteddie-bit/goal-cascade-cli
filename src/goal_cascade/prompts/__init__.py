"""Prompt loader — charge les templates Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

PROMPTS_DIR = Path(__file__).parent


class PromptLoader:
    """Charge et rend les templates de prompts."""

    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.env = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_name: str, **context) -> str:
        """Rend un template avec le contexte donne."""
        template = self.env.get_template(template_name)
        return template.render(**context)
