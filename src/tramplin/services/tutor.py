from dataclasses import dataclass
from typing import Final

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import UnprocessableError
from tramplin.infrastructure.llm import ChatPrompt, ChatTurn
from tramplin.infrastructure.tutor_quota import TutorQuota
from tramplin.services.algorithms import AlgorithmPracticeService
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

ALGORITHM_SYSTEM_PROMPT: Final = """\
Ты — учебный ассистент платформы «Трамплин». Студент решает алгоритмическую задачу
в тренажёре и спрашивает про неё.

Как отвечать:
- По-русски, коротко и по делу.
- Опирайся на условие задачи ниже.
- Никогда не выдавай готовое решение целиком и не пиши код, который проходит все тесты:
  подсказывай идею, подходящую структуру данных, разбирай похожий пример, наводящие
  вопросы, оценку сложности по времени и памяти — но финальный код студент дописывает сам.
- Если студент прислал свой код с ошибкой — укажи, в чём именно она, не переписывая
  решение целиком.
- Небольшой фрагмент-подсказку можно оформить markdown-блоком с языком, но не полный
  проходящий тесты код.

Задача «{title}» (сложность: {difficulty}):
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

    def __init__(
        self,
        lessons: LessonService,
        algorithms: AlgorithmPracticeService,
        quota: TutorQuota,
        settings: Settings,
    ) -> None:
        self._lessons = lessons
        self._algorithms = algorithms
        self._quota = quota
        self._settings = settings

    async def prepare(
        self,
        asker: Asker,
        lesson_id: uuid.UUID,
        turns: list[ChatTurn],
    ) -> ChatPrompt:
        self._validate(turns)
        await self._take_quota(asker)
        lesson = await self._lessons.get(lesson_id)
        return ChatPrompt(
            system=SYSTEM_PROMPT.format(title=lesson.title, body=lesson.body_md),
            turns=turns[-self._settings.llm_history_limit :],
        )

    async def prepare_for_problem(
        self,
        asker: Asker,
        problem_id: uuid.UUID,
        turns: list[ChatTurn],
    ) -> ChatPrompt:
        self._validate(turns)
        await self._take_quota(asker)
        problem = await self._algorithms.get_problem(problem_id)
        return ChatPrompt(
            system=ALGORITHM_SYSTEM_PROMPT.format(
                title=problem.title, difficulty=problem.difficulty, body=problem.statement_md
            ),
            turns=turns[-self._settings.llm_history_limit :],
        )

    async def _take_quota(self, asker: Asker) -> None:
        if asker.user_id is None:
            await self._quota.take_guest(asker.guest_id, asker.ip)
        else:
            await self._quota.take_user(asker.user_id)

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
