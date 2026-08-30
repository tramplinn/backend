import pytest
from pydantic import ValidationError

from tramplin.api.schemas.lessons import LessonCreate
from tramplin.core.errors import InvalidLessonContentError
from tramplin.services.lesson_markdown import render_lesson_content


def test_lesson_markdown_is_rendered_without_raw_html_or_unsafe_links() -> None:
    rendered = render_lesson_content(
        "# Заголовок\n\n<script>alert(1)</script>\n\n[x](javascript:alert(2))",
    )

    assert "<h1>Заголовок</h1>" in rendered.body_html
    assert "<script>" not in rendered.body_html
    assert "&lt;script&gt;" in rendered.body_html
    assert 'href="javascript:' not in rendered.body_html


def test_lesson_markdown_renders_containers_and_highlighted_code() -> None:
    rendered = render_lesson_content(
        ":::note\nВажно **знать**.\n:::\n\n```python\nprint(1)\n```",
    )

    assert '<div class="note">' in rendered.body_html
    assert "<strong>знать</strong>" in rendered.body_html
    assert 'class="language-python"' in rendered.body_html
    assert 'class="nb"' in rendered.body_html


def test_interview_blocks_are_extracted_in_source_order() -> None:
    rendered = render_lesson_content(
        ":::interview\nЧто такое XSS?\n---\nВнедрение скрипта.\n:::",
    )

    assert len(rendered.interview_cards) == 1
    assert rendered.interview_cards[0].position == 0
    assert rendered.interview_cards[0].question_md == "Что такое XSS?"
    assert rendered.interview_cards[0].answer_md == "Внедрение скрипта."


@pytest.mark.parametrize(
    "body_md",
    [
        ":::interview\nВопрос без ответа\n:::",
        ":::interview\nВопрос\n---\nОтвет без закрытия",
    ],
)
def test_invalid_interview_block_is_rejected(body_md: str) -> None:
    with pytest.raises(InvalidLessonContentError):
        render_lesson_content(body_md)


def test_lesson_input_does_not_accept_derived_html() -> None:
    with pytest.raises(ValidationError):
        LessonCreate.model_validate(
            {
                "title": "Урок",
                "slug": "lesson",
                "position": 0,
                "body_md": "# Урок",
                "body_html": "<script>alert(1)</script>",
            },
        )
