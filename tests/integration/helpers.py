import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from redis.asyncio import Redis


def query_param(url: str, name: str) -> str:
    return parse_qs(urlsplit(url).query)[name][0]


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code, response.text


async def issued_email_code(redis: Redis, email: str) -> str:
    """Код из письма: читаем его там же, где его хранит EmailCodeStore."""
    keys = [
        key
        async for key in redis.scan_iter(match="email:otp:*")
        if ":cooldown:" not in key and email in key
    ]
    assert len(keys) == 1, keys
    stored: dict[str, Any] = json.loads(await redis.get(keys[0]) or "{}")
    return str(stored["code"])


async def create(
    client: httpx.AsyncClient, path: str, payload: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    response = await client.post(path, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


INTERVIEW_MD = (
    "# Хэш-таблицы\n\nТекст урока.\n\n"
    ":::interview\nЧто такое коллизия?\n---\nСовпадение хэшей.\n:::\n"
)


async def published_course(
    client: httpx.AsyncClient, headers: dict[str, str], slug: str = "algo"
) -> dict[str, Any]:
    """Курс → модуль → урок с карточкой собеседования → тест с одним вопросом, всё опубликовано."""
    course = await create(
        client, "/authoring/courses", {"title": "Алгоритмы", "slug": slug, "tags": ["cs"]}, headers
    )
    module = await create(
        client,
        f"/authoring/courses/{course['id']}/modules",
        {"title": "Хэши", "slug": "hashes", "position": 0},
        headers,
    )
    lesson = await create(
        client,
        f"/authoring/modules/{module['id']}/lessons",
        {"title": "Хэш-таблицы", "slug": "hash-tables", "body_md": INTERVIEW_MD, "est_minutes": 10},
        headers,
    )
    quiz = await create(
        client,
        f"/authoring/modules/{module['id']}/quizzes",
        {"title": "Проверка", "slug": "check", "lesson_id": lesson["id"]},
        headers,
    )
    question = await create(
        client,
        f"/authoring/quizzes/{quiz['id']}/questions",
        {
            "position": 0,
            "prompt_md": "Сложность поиска?",
            "type": "single",
            "options": ["O(1)", "O(n)"],
            "answer": {"value": "O(1)"},
            "explain_md": "В среднем — константа.",
        },
        headers,
    )
    report = await client.post(f"/authoring/courses/{course['id']}/publish", headers=headers)
    assert report.status_code == 200, report.text
    return {
        "course": course,
        "module": module,
        "lesson": lesson,
        "quiz": quiz,
        "question": question,
    }


SOLUTION = "print(sum(map(int, input().split())))"


async def problem(
    client: httpx.AsyncClient, headers: dict[str, str], slug: str = "a-plus-b"
) -> dict[str, Any]:
    """Опубликованная задача с тестом, проверенным эталонным решением на python."""
    h = headers
    created = await create(
        client,
        "/authoring/algorithms/problems",
        {
            "slug": slug,
            "title": "A + B",
            "statement_md": "Сложите **два** числа.",
            "difficulty": "easy",
            "tags": ["math"],
            "time_limit_ms": 1000,
            "memory_limit_kb": 65536,
        },
        h,
    )
    await create(
        client,
        f"/authoring/algorithms/problems/{created['id']}/test-cases",
        {"position": 0, "input": "1 2", "expected_output": "3", "is_sample": True, "weight": 1},
        h,
    )
    await create(
        client,
        f"/authoring/algorithms/problems/{created['id']}/test-cases",
        {"position": 1, "input": "10 20", "expected_output": "30"},
        h,
    )
    template = await client.put(
        f"/authoring/algorithms/problems/{created['id']}/templates/python",
        json={"language": "python", "starter_code": "# ваш код", "solution_code": SOLUTION},
        headers=h,
    )
    assert template.status_code == 200, template.text
    validated = await client.post(
        f"/authoring/algorithms/problems/{created['id']}/templates/python/validate", headers=h
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["validated_at"] is not None
    published = await client.patch(
        f"/authoring/algorithms/problems/{created['id']}", json={"status": "published"}, headers=h
    )
    assert published.status_code == 200, published.text
    return dict(published.json())
