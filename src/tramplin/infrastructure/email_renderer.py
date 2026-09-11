from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from premailer import transform

from tramplin.services.contracts import RenderedEmail

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"


class EmailRenderer:
    """CSS инлайнится здесь: большинство почтовых клиентов режет <style> в <head>,
    а не инлайновые атрибуты style="..."."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
        )

    def render(self, name: str, context: dict[str, Any]) -> RenderedEmail:
        subject = self._env.get_template(f"{name}.subject.txt.jinja").render(context).strip()
        html = transform(self._env.get_template(f"{name}.html.jinja").render(context))
        text = self._env.get_template(f"{name}.txt.jinja").render(context).strip()
        return RenderedEmail(subject=subject, html=html, text=text)
