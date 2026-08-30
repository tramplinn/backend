from dataclasses import dataclass
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from mdit_py_plugins.container import container_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from tramplin.core.errors import InvalidLessonContentError

CONTAINER_NAMES: Final = ("note", "warning", "pitfall", "spoiler", "interview")


@dataclass(frozen=True, slots=True)
class InterviewCardContent:
    position: int
    question_md: str
    answer_md: str


@dataclass(frozen=True, slots=True)
class RenderedLessonContent:
    body_html: str
    interview_cards: list[InterviewCardContent]


def render_lesson_content(body_md: str) -> RenderedLessonContent:
    cards = _extract_interview_cards(body_md)
    return RenderedLessonContent(
        body_html=_markdown_renderer().render(body_md),
        interview_cards=cards,
    )


def _markdown_renderer() -> MarkdownIt:
    renderer = MarkdownIt(
        "commonmark",
        {
            "html": False,
            "highlight": _highlight_code,
        },
    )
    for name in CONTAINER_NAMES:
        renderer.use(container_plugin, name)
    return renderer


def _highlight_code(code: str, language: str, _attributes: str) -> str:
    if not language:
        return escapeHtml(code)
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return escapeHtml(code)
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def _extract_interview_cards(body_md: str) -> list[InterviewCardContent]:
    lines = body_md.splitlines()
    cards: list[InterviewCardContent] = []
    line_number = 0
    while line_number < len(lines):
        if lines[line_number].strip() != ":::interview":
            line_number += 1
            continue
        closing = _find_closing_marker(lines, line_number + 1)
        content = lines[line_number + 1 : closing]
        try:
            separator = next(index for index, line in enumerate(content) if line.strip() == "---")
        except StopIteration as error:
            raise InvalidLessonContentError(
                "Блок interview должен разделять вопрос и ответ строкой ---",
                line=line_number + 1,
            ) from error
        question = "\n".join(content[:separator]).strip()
        answer = "\n".join(content[separator + 1 :]).strip()
        if not question or not answer:
            raise InvalidLessonContentError(
                "Вопрос и ответ в блоке interview не могут быть пустыми",
                line=line_number + 1,
            )
        cards.append(
            InterviewCardContent(
                position=len(cards),
                question_md=question,
                answer_md=answer,
            ),
        )
        line_number = closing + 1
    return cards


def _find_closing_marker(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index].strip() == ":::":
            return index
    raise InvalidLessonContentError(
        "Блок interview не закрыт маркером :::",
        line=start,
    )
