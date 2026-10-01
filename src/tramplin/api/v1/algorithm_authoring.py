import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.algorithm_mapping import problem_author_out, set_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.indexes import IndexOut, ProblemIndexItemOut, fetch_all
from tramplin.api.schemas.algorithms import (
    PracticeSetCreate,
    PracticeSetOut,
    PracticeSetUpdate,
    ProblemAuthorOut,
    ProblemCreate,
    ProblemUpdate,
    ReorderProblems,
    SetProblemAdd,
    TemplateAuthorOut,
    TemplatePut,
    TestCaseCreate,
    TestCaseOut,
    TestCaseUpdate,
)
from tramplin.api.schemas.pagination import PageOut
from tramplin.core.errors import NotFoundError
from tramplin.models.algorithms import AlgorithmProblem, AlgorithmTestCase, PracticeSet
from tramplin.services.algorithms import AlgorithmAuthoringService
from tramplin.services.entity_updates import require

router = APIRouter(tags=["authoring:algorithms"], route_class=DishkaRoute)


@router.get(
    "/algorithms/problems",
    summary="Список задач (автор)",
    description="Все алгоритмические задачи, включая черновики, для авторской панели.",
)
async def list_problems(
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[ProblemAuthorOut]:
    page = await service.list_problems(limit=limit, offset=offset)
    return PageOut(
        items=[problem_author_out(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/algorithms/problems/index",
    summary="Индекс задач (автор)",
    description="Все задачи, включая черновики, одним ответом: id, slug, title, difficulty.",
)
async def index_problems(
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> IndexOut[ProblemIndexItemOut]:
    items = await fetch_all(lambda limit, offset: service.list_problems(limit=limit, offset=offset))
    return IndexOut(
        items=[ProblemIndexItemOut.model_validate(problem) for problem in items],
        total=len(items),
    )


@router.post(
    "/algorithms/problems",
    status_code=status.HTTP_201_CREATED,
    summary="Создать задачу",
    description="Создаёт задачу как черновик, без тестов и языковых шаблонов решения.",
)
async def create_problem(
    payload: ProblemCreate, user: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> ProblemAuthorOut:
    data = payload.model_dump()
    data["external_url"] = str(data["external_url"]) if data["external_url"] else None
    tag_names = data.pop("tags")
    problem = AlgorithmProblem(statement_html="", **data)
    return problem_author_out(await service.create_problem(problem, tag_names, user.id))


@router.get(
    "/algorithms/problems/slug/{slug}",
    summary="Задача по slug (автор)",
    description="Включает черновики, тесты и служебные поля; используется MCP-сервером для diff.",
)
async def get_problem_by_slug(
    slug: str, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> ProblemAuthorOut:
    problem = require(
        await service.get_problem_by_slug(slug),
        NotFoundError("Алгоритмическая задача не найдена"),
    )
    return problem_author_out(problem)


@router.get(
    "/algorithms/problems/{problem_id}",
    summary="Задача по id (автор)",
    description="Включает черновики, тесты и служебные поля, недоступные публично.",
)
async def get_problem(
    problem_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> ProblemAuthorOut:
    return problem_author_out(await service.get_problem(problem_id))


@router.patch(
    "/algorithms/problems/{problem_id}",
    summary="Изменить задачу",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_problem(
    problem_id: uuid.UUID,
    payload: ProblemUpdate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> ProblemAuthorOut:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("external_url") is not None:
        changes["external_url"] = str(changes["external_url"])
    return problem_author_out(await service.update_problem(problem_id, changes, user.id))


@router.delete(
    "/algorithms/problems/{problem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить задачу",
    description="Безвозвратно удаляет задачу вместе с тестами и шаблонами решений.",
)
async def delete_problem(
    problem_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> None:
    await service.delete_problem(problem_id)


@router.post(
    "/algorithms/problems/{problem_id}/test-cases",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить тест-кейс",
    description="Добавляет тест-кейс для проверки решений задачи.",
)
async def add_case(
    problem_id: uuid.UUID,
    payload: TestCaseCreate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TestCaseOut:
    case = AlgorithmTestCase(problem_id=problem_id, **payload.model_dump())
    return TestCaseOut.model_validate(await service.add_case(problem_id, case, user.id))


@router.patch(
    "/algorithms/test-cases/{case_id}",
    summary="Изменить тест-кейс",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_case(
    case_id: uuid.UUID,
    payload: TestCaseUpdate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TestCaseOut:
    return TestCaseOut.model_validate(
        await service.update_case(case_id, payload.model_dump(exclude_unset=True), user.id)
    )


@router.delete(
    "/algorithms/test-cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить тест-кейс",
    description="Безвозвратно удаляет тест-кейс задачи.",
)
async def delete_case(
    case_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> None:
    await service.delete_case(case_id)


@router.put(
    "/algorithms/problems/{problem_id}/templates/{language}",
    summary="Задать шаблон решения для языка",
    description="Заменяет стартовый код и эталонное решение задачи для указанного языка.",
)
async def put_template(
    problem_id: uuid.UUID,
    language: str,
    payload: TemplatePut,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TemplateAuthorOut:
    if language != payload.language:
        from tramplin.core.errors import ConflictError

        raise ConflictError("Язык в адресе и теле запроса не совпадает")
    return TemplateAuthorOut.model_validate(
        await service.put_template(
            problem_id, language, payload.starter_code, payload.solution_code, user.id
        )
    )


@router.post(
    "/algorithms/problems/{problem_id}/templates/{language}/validate",
    summary="Проверить эталонное решение",
    description="Прогоняет эталонное решение по всем тест-кейсам и проставляет validated_at.",
)
async def validate_template(
    problem_id: uuid.UUID,
    language: str,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TemplateAuthorOut:
    return TemplateAuthorOut.model_validate(
        await service.validate_template(problem_id, language, user.id)
    )


@router.delete(
    "/algorithms/problems/{problem_id}/templates/{language}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить шаблон решения для языка",
    description="Убирает возможность решать задачу на этом языке.",
)
async def delete_template(
    problem_id: uuid.UUID,
    language: str,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.delete_template(problem_id, language)


@router.post(
    "/modules/{module_id}/practice-sets",
    status_code=status.HTTP_201_CREATED,
    summary="Создать набор практики",
    description="Создаёт набор практики в модуле как черновик, без задач.",
)
async def create_set(
    module_id: uuid.UUID,
    payload: PracticeSetCreate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    return set_out(
        await service.create_set(module_id, PracticeSet(**payload.model_dump()), user.id)
    )


@router.get(
    "/practice-sets/{set_id}",
    summary="Набор практики по id (автор)",
    description="Включает черновик набора и его задачи.",
)
async def get_set(
    set_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> PracticeSetOut:
    return set_out(await service.get_set(set_id))


@router.patch(
    "/practice-sets/{set_id}",
    summary="Изменить набор практики",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_set(
    set_id: uuid.UUID,
    payload: PracticeSetUpdate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    return set_out(
        await service.update_set(set_id, payload.model_dump(exclude_unset=True), user.id)
    )


@router.delete(
    "/practice-sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить набор практики",
    description="Безвозвратно удаляет набор вместе со списком его задач.",
)
async def delete_set(
    set_id: uuid.UUID,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.delete_set(set_id)


@router.post(
    "/practice-sets/{set_id}/problems",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить задачу в набор",
    description="Добавляет задачу в конец набора с рекомендованным временем на решение.",
)
async def add_set_problem(
    set_id: uuid.UUID,
    payload: SetProblemAdd,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    await service.add_set_problem(set_id, payload.problem_id, payload.recommended_minutes, user.id)
    return set_out(await service.get_set(set_id))


@router.put(
    "/practice-sets/{set_id}/problems/order",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Задать порядок задач в наборе",
    description="Полностью заменяет порядок: список должен содержать все id задач набора.",
)
async def reorder_set(
    set_id: uuid.UUID,
    payload: ReorderProblems,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.reorder_set(set_id, payload.problem_ids, user.id)


@router.delete(
    "/practice-sets/{set_id}/problems/{problem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать задачу из набора",
    description="Убирает задачу из набора практики, не удаляя саму задачу.",
)
async def remove_set_problem(
    set_id: uuid.UUID,
    problem_id: uuid.UUID,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.remove_set_problem(set_id, problem_id)
