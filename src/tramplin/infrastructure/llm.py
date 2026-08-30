import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from tramplin.core.config import Settings
from tramplin.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """Реплика диалога. system сюда не попадает — его задаёт сервис."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ChatPrompt:
    system: str
    turns: Sequence[ChatTurn]


def _as_param(turn: ChatTurn) -> ChatCompletionMessageParam:
    """Разбор по ветвям: типам SDK нужен литерал роли, а не строка."""
    if turn.role == "user":
        return {"role": "user", "content": turn.content}
    return {"role": "assistant", "content": turn.content}


class LlmClient:
    """Клиент к любому OpenAI-совместимому /chat/completions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value() or "not-configured",
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout.total_seconds(),
            max_retries=settings.llm_retries,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[str]:
        if not self._settings.llm_enabled:
            raise ServiceUnavailableError("Ассистент не настроен")

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompt.system},
            *(_as_param(turn) for turn in prompt.turns),
        ]

        try:
            # async with обязателен: без него соединение к провайдеру висит
            # в пуле до сборщика мусора.
            async with await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,
                max_tokens=self._settings.llm_max_tokens,
                temperature=self._settings.llm_temperature,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except openai.APIStatusError as error:
            # Тело ответа не логируем: в нём может быть ключ.
            logger.warning("Провайдер модели ответил %s", error.status_code)
            raise ServiceUnavailableError("Ассистент сейчас недоступен") from error
        except openai.APIError as error:
            logger.warning("Ошибка обращения к модели: %s", type(error).__name__)
            raise ServiceUnavailableError("Ассистент сейчас недоступен") from error
