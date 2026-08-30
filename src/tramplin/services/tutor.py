from dataclasses import dataclass
from typing import Final

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import UnprocessableError
from tramplin.infrastructure.llm import ChatPrompt, ChatTurn
from tramplin.infrastructure.tutor_quota import TutorQuota
from tramplin.services.lessons import LessonService

SYSTEM_PROMPT: Final = """\
Ты — учебный ассистент платформы «Трамплин». Студент читает урок и спрашивает по нему.

Как отвечать:
- По-русски, коротко и по делу. Три-четыре предложения, если вопрос не требует большего.
- Опирайся на текст урока ниже. Если ответа в нём нет, скажи об этом прямо и ответь
  из общих знаний, отметив, что это уже за рамками урока.
- Не выдумывай факты о курсе, преподавателе, сроках и заданиях: чего нет в уроке —
  того ты не знаешь.
- Просят решить тест или контрольную — объясни принцип и разбери похожий пример,
  но готовый ответ не давай.
- Код оформляй markdown-блоком с указанием языка.

Урок «{title}»:
{body}
"""


@dataclass(frozen=True, slots=True)
class Asker:
    """Кто спрашивает: у гостя своя, узкая квота."""

    guest_id: str
    user_id: uuid.UUID | None = None
    ip: str | None = None


class TutorService:
    """Собирает запрос к модели; поток ответа идёт мимо сервиса."""

    def __init__(self, lessons: LessonService, quota: TutorQuota, settings: Settings) -> None:
        self._lessons = lessons
        self._quota = quota
        self._settings = settings

    async def prepare(
        self,
        asker: Asker,
        lesson_id: uuid.UUID,
        turns: list[ChatTurn],
    ) -> ChatPrompt:
        self._validate(turns)
        if asker.user_id is None:
            await self._quota.take_guest(asker.guest_id, asker.ip)
        else:
            await self._quota.take_user(asker.user_id)
        lesson = await self._lessons.get(lesson_id)
        return ChatPrompt(
            system=SYSTEM_PROMPT.format(title=lesson.title, body=lesson.body_md),
            turns=turns[-self._settings.llm_history_limit :],
        )

    def _validate(self, turns: list[ChatTurn]) -> None:
        if not turns or turns[-1].role != "user":
            raise UnprocessableError("Последняя реплика должна быть вопросом студента")
        question = turns[-1].content.strip()
        if not question:
            raise UnprocessableError("Пустой вопрос")
        if len(question) > self._settings.llm_question_max_chars:
            raise UnprocessableError(
                f"Вопрос длиннее {self._settings.llm_question_max_chars} символов",
            )
