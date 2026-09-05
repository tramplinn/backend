import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

import openai
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from tramplin.core.config import Settings
from tramplin.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)
StructuredT = TypeVar("StructuredT", bound=BaseModel)


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
        timeout = settings.llm_timeout.total_seconds()
        self._http_client = (
            DefaultAsyncHttpxClient(proxy=settings.llm_proxy_url, timeout=timeout)
            if settings.llm_proxy_url
            else None
        )
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value() or "not-configured",
            base_url=settings.llm_base_url,
            timeout=timeout,
            max_retries=settings.llm_retries,
            http_client=self._http_client,
        )

    async def aclose(self) -> None:
        await self._client.close()
        if self._http_client is not None:
            await self._http_client.aclose()

    def _attempts(self) -> list[str]:
        """Каждый кандидат пробуем хотя бы раз, одинокую модель — ещё и повторно."""
        candidates = [self._settings.llm_model, *self._settings.llm_fallbacks]
        total = max(len(candidates), self._settings.llm_stream_retries + 1)
        return [candidates[index % len(candidates)] for index in range(total)]

    def _log(self, model: str, error: openai.APIError) -> None:
        if isinstance(error, openai.APIStatusError):
            logger.warning("Модель %s: провайдер ответил %s", model, error.status_code)
        else:
            logger.warning("Модель %s: %s — %s", model, type(error).__name__, error.message)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Эмбеддинги идемпотентны и не стримятся — без ретраев/фолбэков, как у чата."""
        if not self._settings.embeddings_enabled:
            raise ServiceUnavailableError("Эмбеддинги не настроены")

        response = await self._client.embeddings.create(
            model=self._settings.embedding_model,
            input=list(texts),
            dimensions=self._settings.embedding_dimensions,
        )
        return [item.embedding for item in response.data]

    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[str]:
        if not self._settings.llm_enabled:
            raise ServiceUnavailableError("Ассистент не настроен")

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompt.system},
            *(_as_param(turn) for turn in prompt.turns),
        ]

        attempts = self._attempts()
        for index, model in enumerate(attempts):
            started = False
            try:
                async with await self._client.chat.completions.create(
                    model=model,
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
                            started = True
                            yield delta
            except openai.APIError as error:
                self._log(model, error)
                if started or index == len(attempts) - 1:
                    raise ServiceUnavailableError("Ассистент сейчас недоступен") from error
                continue
            return

    async def structured(
        self,
        prompt: ChatPrompt,
        result_type: type[StructuredT],
        *,
        max_output_tokens: int,
    ) -> StructuredT:
        """Структурированный ответ для действий интерфейса, а не свободного чата."""
        if not self._settings.llm_enabled:
            raise ServiceUnavailableError("Ассистент не настроен")

        input_text = "\n\n".join(
            f"{('Пользователь' if turn.role == 'user' else 'Ассистент')}: {turn.content}"
            for turn in prompt.turns
        )
        attempts = self._attempts()
        for index, model in enumerate(attempts):
            last = index == len(attempts) - 1
            try:
                response = await self._client.responses.parse(
                    model=model,
                    instructions=prompt.system,
                    input=input_text,
                    text_format=result_type,
                    max_output_tokens=max_output_tokens,
                    store=False,
                )
            except openai.APIError as error:
                self._log(model, error)
                if last:
                    raise ServiceUnavailableError("Ассистент сейчас недоступен") from error
                continue
            if response.output_parsed is not None:
                return response.output_parsed
            logger.warning("Модель %s: ответ не прошёл структурный разбор", model)
            if last:
                raise ServiceUnavailableError("Ассистент не смог подготовить правки")
        raise ServiceUnavailableError("Ассистент сейчас недоступен")
