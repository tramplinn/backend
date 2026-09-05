from typing import Any

import pytest
from pydantic import SecretStr

from tramplin.core.config import Settings
from tramplin.core.errors import UnprocessableError
from tramplin.services.teacher_assistant import (
    AuthoringDocument,
    AuthoringPatch,
    TeacherAssistantService,
)


class FakeLlm:
    def __init__(self, result: AuthoringPatch) -> None:
        self.result = result
        self.prompt: Any = None

    async def structured(self, prompt: Any, result_type: Any, *, max_output_tokens: int) -> Any:
        self.prompt = prompt
        assert result_type is AuthoringPatch
        assert max_output_tokens == 4000
        return self.result


def settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr("test-secret-value-at-least-32-bytes"),
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
    )


async def test_lesson_suggestion_contains_current_draft() -> None:
    llm = FakeLlm(AuthoringPatch(explanation="Исправил", body_md="# Новый текст"))
    service = TeacherAssistantService(llm, settings())  # type: ignore[arg-type]

    result = await service.suggest(
        "lesson",
        "Сделай понятнее",
        AuthoringDocument(title="Урок", body_md="# Старый текст"),
    )

    assert result.body_md == "# Новый текст"
    assert "Сделай понятнее" in llm.prompt.turns[0].content
    assert "Старый текст" in llm.prompt.turns[0].content


async def test_assistant_rejects_fields_from_another_editor() -> None:
    llm = FakeLlm(AuthoringPatch(explanation="Готово", statement_md="Условие"))
    service = TeacherAssistantService(llm, settings())  # type: ignore[arg-type]

    with pytest.raises(UnprocessableError):
        await service.suggest(
            "lesson",
            "Исправь",
            AuthoringDocument(title="Урок", body_md="Текст"),
        )


async def test_assistant_rejects_blank_request() -> None:
    llm = FakeLlm(AuthoringPatch(explanation="Готово"))
    service = TeacherAssistantService(llm, settings())  # type: ignore[arg-type]

    with pytest.raises(UnprocessableError):
        await service.suggest(
            "algorithm_problem",
            "   ",
            AuthoringDocument(title="Задача", statement_md="Условие"),
        )
