import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest
import uuid_utils.compat as uuid
from pydantic import BaseModel, SecretStr

from tramplin.core.config import Settings
from tramplin.core.errors import (
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnprocessableError,
)
from tramplin.infrastructure.llm import ChatPrompt, ChatTurn, LlmClient, _as_param
from tramplin.infrastructure.tutor_quota import TutorQuota
from tramplin.models.algorithms import AlgorithmProblem
from tramplin.models.content import Lesson
from tramplin.models.enums import AlgorithmDifficulty
from tramplin.services.tutor import Asker, TutorService


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True


class FakeLessons:
    def __init__(self, lesson: Lesson | None) -> None:
        self._lesson = lesson

    async def get(self, lesson_id: uuid.UUID, *, published_only: bool = True) -> Lesson:
        if self._lesson is None:
            raise NotFoundError("Урок не найден")
        return self._lesson


class FakeAlgorithms:
    def __init__(self, problem: AlgorithmProblem | None) -> None:
        self._problem = problem

    async def get_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem:
        if self._problem is None:
            raise NotFoundError("Алгоритмическая задача не найдена")
        return self._problem


def make_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr("test-secret-value-at-least-32-bytes"),
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
        **overrides,
    )


def make_lesson() -> Lesson:
    lesson = Lesson()
    lesson.id = uuid.uuid7()
    lesson.title = "Переменные и функции"
    lesson.body_md = "Переменная — именованная ячейка."
    return lesson


def make_problem() -> AlgorithmProblem:
    problem = AlgorithmProblem()
    problem.id = uuid.uuid7()
    problem.title = "Две суммы"
    problem.difficulty = AlgorithmDifficulty.EASY
    problem.statement_md = "Найдите два числа в массиве, дающих в сумме target."
    return problem


def make_service(
    *,
    lessons: FakeLessons | None = None,
    algorithms: FakeAlgorithms | None = None,
    redis: FakeRedis | None = None,
    **overrides: Any,
) -> TutorService:
    settings = make_settings(**overrides)
    quota = TutorQuota(redis or FakeRedis(), settings)  # type: ignore[arg-type]  # фейк реализует нужные два метода
    return TutorService(
        lessons or FakeLessons(make_lesson()),  # type: ignore[arg-type]  # фейк повторяет протокол get
        algorithms or FakeAlgorithms(make_problem()),  # type: ignore[arg-type]  # фейк повторяет get_problem
        quota,
        settings,
    )


def student(user_id: uuid.UUID | None = None) -> Asker:
    return Asker(guest_id=str(uuid.uuid4()), user_id=user_id or uuid.uuid7())


def guest(guest_id: str = "guest-1", ip: str | None = "10.0.0.1") -> Asker:
    return Asker(guest_id=guest_id, ip=ip)


async def test_prepare_puts_lesson_text_into_system_prompt() -> None:
    service = make_service()

    prompt = await service.prepare(
        student(),
        uuid.uuid7(),
        [ChatTurn(role="user", content="что такое переменная?")],
    )

    assert "Переменные и функции" in prompt.system
    assert "именованная ячейка" in prompt.system
    assert len(prompt.turns) == 1


async def test_prepare_keeps_only_recent_turns() -> None:
    service = make_service(llm_history_limit=4)
    history = [
        ChatTurn(role="user" if index % 2 == 0 else "assistant", content=f"реплика {index}")
        for index in range(9)
    ]

    prompt = await service.prepare(student(), uuid.uuid7(), history)

    assert len(prompt.turns) == 4
    assert prompt.turns[-1].content == "реплика 8"


async def test_prepare_rejects_history_not_ending_with_question() -> None:
    service = make_service()

    with pytest.raises(UnprocessableError):
        await service.prepare(
            student(),
            uuid.uuid7(),
            [ChatTurn(role="assistant", content="ответ")],
        )


async def test_prepare_rejects_blank_and_overlong_question() -> None:
    service = make_service(llm_question_max_chars=10)

    with pytest.raises(UnprocessableError):
        await service.prepare(student(), uuid.uuid7(), [ChatTurn(role="user", content="   ")])

    with pytest.raises(UnprocessableError):
        await service.prepare(
            student(),
            uuid.uuid7(),
            [ChatTurn(role="user", content="в" * 11)],
        )


async def test_prepare_rejects_empty_dialogue() -> None:
    service = make_service()

    with pytest.raises(UnprocessableError):
        await service.prepare(student(), uuid.uuid7(), [])


async def test_quota_counts_per_user_and_day_then_refuses() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_daily_quota=2)
    user = student()
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(user, uuid.uuid7(), question)
    await service.prepare(user, uuid.uuid7(), question)

    with pytest.raises(TooManyRequestsError):
        await service.prepare(user, uuid.uuid7(), question)

    key = next(iter(redis.counters))
    assert str(user.user_id) in key
    assert redis.expires[key] > 0
    assert redis.counters[key] == 3


async def test_quota_is_separate_for_another_user() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_daily_quota=1)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(student(), uuid.uuid7(), question)
    await service.prepare(student(), uuid.uuid7(), question)

    assert len(redis.counters) == 2


async def test_guest_gets_a_few_questions_then_is_asked_to_sign_in() -> None:
    redis = FakeRedis()
    service = make_service(
        redis=redis,
        llm_guest_quota=2,
        llm_guest_ip_quota=100,
        llm_guest_daily_total=100,
    )
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest(), uuid.uuid7(), question)
    await service.prepare(guest(), uuid.uuid7(), question)

    with pytest.raises(TooManyRequestsError, match="Войдите"):
        await service.prepare(guest(), uuid.uuid7(), question)


async def test_guest_quota_is_wider_for_authenticated_student() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_guest_quota=1, llm_daily_quota=5)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest(), uuid.uuid7(), question)
    with pytest.raises(TooManyRequestsError):
        await service.prepare(guest(), uuid.uuid7(), question)

    for _ in range(5):
        await service.prepare(student(), uuid.uuid7(), question)


async def test_address_limit_catches_guest_cycling_cookies() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_guest_quota=10, llm_guest_ip_quota=2)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest("cookie-1"), uuid.uuid7(), question)
    await service.prepare(guest("cookie-2"), uuid.uuid7(), question)

    with pytest.raises(TooManyRequestsError, match="адреса"):
        await service.prepare(guest("cookie-3"), uuid.uuid7(), question)


async def test_exhausted_guest_does_not_burn_the_shared_address_limit() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_guest_quota=1, llm_guest_ip_quota=10)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest(), uuid.uuid7(), question)
    with pytest.raises(TooManyRequestsError):
        await service.prepare(guest(), uuid.uuid7(), question)

    address_keys = [key for key in redis.counters if ":ip:" in key]
    assert redis.counters[address_keys[0]] == 1


async def test_shared_daily_cap_holds_even_when_cookies_and_addresses_change() -> None:
    redis = FakeRedis()
    service = make_service(
        redis=redis,
        llm_guest_quota=10,
        llm_guest_ip_quota=10,
        llm_guest_daily_total=2,
    )
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest("cookie-1", "10.0.0.1"), uuid.uuid7(), question)
    await service.prepare(guest("cookie-2", "10.0.0.2"), uuid.uuid7(), question)

    with pytest.raises(TooManyRequestsError, match="разобрали"):
        await service.prepare(guest("cookie-3", "10.0.0.3"), uuid.uuid7(), question)


async def test_shared_daily_cap_does_not_touch_signed_in_students() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_guest_daily_total=1, llm_daily_quota=5)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest(), uuid.uuid7(), question)
    with pytest.raises(TooManyRequestsError):
        await service.prepare(guest(), uuid.uuid7(), question)

    for _ in range(5):
        await service.prepare(student(), uuid.uuid7(), question)


async def test_guest_without_known_address_is_still_limited() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_guest_quota=1)
    question = [ChatTurn(role="user", content="вопрос")]

    await service.prepare(guest(ip=None), uuid.uuid7(), question)

    with pytest.raises(TooManyRequestsError):
        await service.prepare(guest(ip=None), uuid.uuid7(), question)


async def test_prepare_reports_missing_lesson() -> None:
    service = make_service(lessons=FakeLessons(None))

    with pytest.raises(NotFoundError):
        await service.prepare(
            student(),
            uuid.uuid7(),
            [ChatTurn(role="user", content="вопрос")],
        )


async def test_prepare_for_problem_puts_statement_into_system_prompt() -> None:
    service = make_service()

    prompt = await service.prepare_for_problem(
        student(),
        uuid.uuid7(),
        [ChatTurn(role="user", content="с чего начать?")],
    )

    assert "Две суммы" in prompt.system
    assert "дающих в сумме target" in prompt.system
    assert len(prompt.turns) == 1


async def test_prepare_for_problem_never_asks_for_the_full_solution() -> None:
    service = make_service()

    prompt = await service.prepare_for_problem(
        student(),
        uuid.uuid7(),
        [ChatTurn(role="user", content="дай готовое решение")],
    )

    assert "не выдавай готовое решение" in prompt.system.lower()


async def test_prepare_for_problem_reports_missing_problem() -> None:
    service = make_service(algorithms=FakeAlgorithms(None))

    with pytest.raises(NotFoundError):
        await service.prepare_for_problem(
            student(),
            uuid.uuid7(),
            [ChatTurn(role="user", content="вопрос")],
        )


async def test_prepare_for_problem_shares_the_quota_with_lesson_questions() -> None:
    redis = FakeRedis()
    service = make_service(redis=redis, llm_daily_quota=1)
    user = student()

    await service.prepare(user, uuid.uuid7(), [ChatTurn(role="user", content="вопрос")])

    with pytest.raises(TooManyRequestsError):
        await service.prepare_for_problem(
            user,
            uuid.uuid7(),
            [ChatTurn(role="user", content="вопрос")],
        )


async def test_client_refuses_to_call_provider_until_configured() -> None:
    client = LlmClient(make_settings())

    stream = client.stream(ChatPrompt(system="s", turns=[ChatTurn(role="user", content="q")]))
    with pytest.raises(ServiceUnavailableError):
        await anext(stream)


def test_turns_map_to_provider_roles() -> None:
    assert _as_param(ChatTurn(role="user", content="q")) == {"role": "user", "content": "q"}
    assert _as_param(ChatTurn(role="assistant", content="a")) == {
        "role": "assistant",
        "content": "a",
    }


async def test_route_stream_reports_error_as_event_not_broken_response() -> None:
    from tramplin.api.v1.tutor import _events

    class FailingClient:
        async def stream(self, prompt: ChatPrompt) -> AsyncIterator[str]:
            yield "часть ответа"
            raise ServiceUnavailableError("Ассистент сейчас недоступен")

    events = [
        event
        async for event in _events(
            FailingClient(),  # type: ignore[arg-type]  # фейк повторяет единственный используемый метод
            ChatPrompt(system="s", turns=[]),
        )
    ]

    assert '"delta": "часть ответа"' in events[0]
    assert "Ассистент сейчас недоступен" in events[-1]
    assert not any('"done"' in event for event in events)


async def test_route_stream_closes_with_done() -> None:
    from tramplin.api.v1.tutor import _events

    class OkClient:
        async def stream(self, prompt: ChatPrompt) -> AsyncIterator[str]:
            yield "ответ"

    events = [
        event
        async for event in _events(OkClient(), ChatPrompt(system="s", turns=[]))  # type: ignore[arg-type]  # тот же фейк
    ]

    assert events[-1] == 'data: {"done": true}\n\n'


class FakeProviderStream:
    """Ответ провайдера: отдаёт куски, а затем, если задано, падает."""

    def __init__(self, deltas: list[str], error: Exception | None) -> None:
        self._deltas = deltas
        self._error = error

    async def __aenter__(self) -> FakeProviderStream:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def __aiter__(self) -> AsyncIterator[Any]:
        for delta in self._deltas:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=delta))])
        if self._error is not None:
            raise self._error


class FakeCompletions:
    def __init__(self, answers: list[tuple[list[str], Exception | None]]) -> None:
        self._answers = answers
        self.models: list[str] = []

    async def create(self, **kwargs: Any) -> FakeProviderStream:
        model = kwargs["model"]
        self.models.append(model)
        deltas, error = self._answers[len(self.models) - 1]
        return FakeProviderStream(deltas, error)


def make_client(
    answers: list[tuple[list[str], Exception | None]],
    **overrides: Any,
) -> tuple[LlmClient, FakeCompletions]:
    settings = make_settings(llm_model="primary", llm_api_key=SecretStr("k"), **overrides)
    client = LlmClient(settings)
    completions = FakeCompletions(answers)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]  # подменяем SDK целиком
    return client, completions


def overloaded() -> openai.APIError:
    # httpx2 — тот httpx, на котором собран openai; свой httpx у нас другой мажор.
    return openai.APIError(
        "Upstream error from Nvidia: Service temporarily overloaded",
        httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        body=None,
    )


def ask() -> ChatPrompt:
    return ChatPrompt(system="s", turns=[ChatTurn(role="user", content="q")])


async def test_stream_falls_back_to_next_model_when_provider_fails_before_first_token() -> None:
    client, completions = make_client(
        [([], overloaded()), (["ответ"], None)],
        llm_fallback_models="spare",
    )

    assert [delta async for delta in client.stream(ask())] == ["ответ"]
    assert completions.models == ["primary", "spare"]


async def test_stream_retries_the_only_model_when_no_fallback_configured() -> None:
    client, completions = make_client([([], overloaded()), (["ответ"], None)])

    assert [delta async for delta in client.stream(ask())] == ["ответ"]
    assert completions.models == ["primary", "primary"]


async def test_stream_does_not_restart_after_answer_started() -> None:
    client, completions = make_client(
        [(["нача"], overloaded()), (["ответ"], None)],
        llm_fallback_models="spare",
    )

    stream = client.stream(ask())
    assert await anext(stream) == "нача"
    with pytest.raises(ServiceUnavailableError):
        await anext(stream)
    assert completions.models == ["primary"]


async def test_stream_gives_up_when_every_candidate_fails() -> None:
    client, completions = make_client(
        [([], overloaded()), ([], overloaded())],
        llm_fallback_models="spare",
    )

    with pytest.raises(ServiceUnavailableError):
        async for _ in client.stream(ask()):
            pass
    assert completions.models == ["primary", "spare"]


class Patch(BaseModel):
    value: str


class FakeParsedResponse:
    def __init__(self, output_parsed: Patch | None) -> None:
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, answers: list[tuple[Patch | None, Exception | None]]) -> None:
        self._answers = answers
        self.models: list[str] = []

    async def parse(self, **kwargs: Any) -> FakeParsedResponse:
        model = kwargs["model"]
        self.models.append(model)
        output, error = self._answers[len(self.models) - 1]
        if error is not None:
            raise error
        return FakeParsedResponse(output)


def make_structured_client(
    answers: list[tuple[Patch | None, Exception | None]],
    **overrides: Any,
) -> tuple[LlmClient, FakeResponses]:
    settings = make_settings(llm_model="primary", llm_api_key=SecretStr("k"), **overrides)
    client = LlmClient(settings)
    responses = FakeResponses(answers)
    client._client = SimpleNamespace(responses=responses)  # type: ignore[assignment]  # подменяем SDK целиком
    return client, responses


async def test_structured_falls_back_when_model_fails_to_produce_parseable_output() -> None:
    client, responses = make_structured_client(
        [(None, None), (Patch(value="ok"), None)],
        llm_fallback_models="spare",
    )

    result = await client.structured(ask(), Patch, max_output_tokens=100)

    assert result == Patch(value="ok")
    assert responses.models == ["primary", "spare"]


async def test_structured_falls_back_to_next_model_on_provider_error() -> None:
    client, responses = make_structured_client(
        [(None, overloaded()), (Patch(value="ok"), None)],
        llm_fallback_models="spare",
    )

    result = await client.structured(ask(), Patch, max_output_tokens=100)

    assert result == Patch(value="ok")
    assert responses.models == ["primary", "spare"]


async def test_structured_gives_up_when_every_candidate_fails_to_parse() -> None:
    client, responses = make_structured_client(
        [(None, None), (None, None)],
        llm_fallback_models="spare",
    )

    with pytest.raises(ServiceUnavailableError, match="не смог подготовить правки"):
        await client.structured(ask(), Patch, max_output_tokens=100)
    assert responses.models == ["primary", "spare"]


async def test_structured_gives_up_when_every_candidate_errors() -> None:
    client, responses = make_structured_client(
        [(None, overloaded()), (None, overloaded())],
        llm_fallback_models="spare",
    )

    with pytest.raises(ServiceUnavailableError, match="недоступен"):
        await client.structured(ask(), Patch, max_output_tokens=100)
    assert responses.models == ["primary", "spare"]


async def test_heartbeat_fills_a_pause_and_keeps_the_events() -> None:
    from tramplin.api.v1.tutor import _HEARTBEAT, _with_heartbeat

    async def slow() -> AsyncGenerator[str]:
        await asyncio.sleep(0.05)
        yield "data: 1\n\n"

    events = [event async for event in _with_heartbeat(slow(), 0.01)]

    assert events[-1] == "data: 1\n\n"
    assert events.count(_HEARTBEAT) >= 1


async def test_heartbeat_is_silent_when_the_stream_is_quick() -> None:
    from tramplin.api.v1.tutor import _with_heartbeat

    async def quick() -> AsyncGenerator[str]:
        yield "data: 1\n\n"

    assert [event async for event in _with_heartbeat(quick(), 5)] == ["data: 1\n\n"]
