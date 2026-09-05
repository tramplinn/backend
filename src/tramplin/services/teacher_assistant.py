import json
from dataclasses import asdict, dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from tramplin.core.config import Settings
from tramplin.core.errors import UnprocessableError
from tramplin.infrastructure.llm import ChatPrompt, ChatTurn, LlmClient

AuthoringSurface = Literal["lesson", "algorithm_problem"]
Difficulty = Literal["easy", "medium", "hard"]

SYSTEM_PROMPT: Final = """\
Ты — помощник преподавателя образовательной платформы «Трамплин».
Подготовь только предложенные правки текущего черновика по просьбе преподавателя.

Правила:
- Пиши по-русски ясно и без канцелярита, если преподаватель не попросил иначе.
- Сохраняй Markdown и техническую точность. Не выдумывай источники, сроки и факты курса.
- Меняй только нужные поля: остальные верни как null.
- Для lesson доступны title и body_md.
- Для algorithm_problem доступны title, statement_md, difficulty, tags, time_limit_ms,
  memory_limit_kb. Условие должно однозначно описывать ввод, вывод, ограничения и пример.
- Не публикуй, не удаляй и не утверждай, что правки уже применены.
- explanation — короткое объяснение результата для преподавателя.
"""


@dataclass(frozen=True, slots=True)
class AuthoringDocument:
    title: str
    body_md: str | None = None
    statement_md: str | None = None
    difficulty: Difficulty | None = None
    tags: list[str] | None = None
    time_limit_ms: int | None = None
    memory_limit_kb: int | None = None


class AuthoringPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=1200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=50000)
    statement_md: str | None = Field(default=None, max_length=50000)
    difficulty: Difficulty | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    time_limit_ms: int | None = Field(default=None, ge=50, le=5000)
    memory_limit_kb: int | None = Field(default=None, ge=16384, le=524288)


class TeacherAssistantService:
    def __init__(self, client: LlmClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def suggest(
        self,
        surface: AuthoringSurface,
        instruction: str,
        document: AuthoringDocument,
    ) -> AuthoringPatch:
        request = instruction.strip()
        if not request:
            raise UnprocessableError("Пустая просьба")
        payload = json.dumps(asdict(document), ensure_ascii=False)
        if len(request) + len(payload) > self._settings.llm_authoring_input_max_chars:
            raise UnprocessableError("Черновик слишком большой для помощника")
        self._validate_document(surface, document)
        result = await self._client.structured(
            ChatPrompt(
                system=SYSTEM_PROMPT,
                turns=[
                    ChatTurn(
                        role="user",
                        content=(
                            f"Экран: {surface}\nПросьба: {request}\nТекущий черновик:\n{payload}"
                        ),
                    ),
                ],
            ),
            AuthoringPatch,
            max_output_tokens=self._settings.llm_authoring_max_tokens,
        )
        self._validate_patch(surface, result)
        return result

    @staticmethod
    def _validate_document(surface: AuthoringSurface, document: AuthoringDocument) -> None:
        if surface == "lesson" and document.body_md is None:
            raise UnprocessableError("Для урока не передан текст")
        if surface == "algorithm_problem" and document.statement_md is None:
            raise UnprocessableError("Для задачи не передано условие")

    @staticmethod
    def _validate_patch(surface: AuthoringSurface, patch: AuthoringPatch) -> None:
        lesson_only = patch.body_md is not None
        algorithm_only = any(
            value is not None
            for value in (
                patch.statement_md,
                patch.difficulty,
                patch.tags,
                patch.time_limit_ms,
                patch.memory_limit_kb,
            )
        )
        if surface == "lesson" and algorithm_only:
            raise UnprocessableError("Ассистент предложил поля другого редактора")
        if surface == "algorithm_problem" and lesson_only:
            raise UnprocessableError("Ассистент предложил поля другого редактора")
