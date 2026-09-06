from typing import Annotated

import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.algorithm_mapping import (
    problem_card_out,
    problem_out,
    set_out,
    solution_out,
    submission_out,
)
from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas.algorithms import (
    CompleteSession,
    PracticeSessionOut,
    PracticeSetOut,
    ProblemCatalogOut,
    ProblemOut,
    ProgressOut,
    ReflectionUpdate,
    RunCreate,
    RunnerLanguageOut,
    SolutionOut,
    SubmissionCreate,
    SubmissionOut,
)
from tramplin.api.tag_mapping import tag_out
from tramplin.models.enums import AlgorithmDifficulty, SubmissionKind
from tramplin.services.algorithms import AlgorithmPracticeService
from tramplin.services.contracts import CodeRunner

router = APIRouter(tags=["algorithms"], route_class=DishkaRoute)


@router.get(
    "/algorithms/problems",
    summary="Каталог алгоритмических задач",
    description="Опубликованные задачи с фильтрами и прогрессом текущего пользователя.",
)
async def list_catalog(
    user: CurrentUser,
    service: FromDishka[AlgorithmPracticeService],
    difficulty: AlgorithmDifficulty | None = None,
    tag_id: uuid.UUID | None = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProblemCatalogOut:
    catalog = await service.list_catalog(
        user.id, difficulty=difficulty, tag_id=tag_id, query=query, limit=limit, offset=offset
    )
    return ProblemCatalogOut(
        items=[problem_card_out(problem, progress) for problem, progress in catalog.items],
        tags=[tag_out(tag) for tag in catalog.tags],
        total=catalog.total,
    )


@router.post(
    "/practice-sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Начать свободную тренировку",
    description="Сессия вне набора практики — нужна для отправки решений из каталога.",
)
async def start_free_session(
    user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> PracticeSessionOut:
    return PracticeSessionOut.model_validate(await service.start_free_session(user.id))


@router.get(
    "/practice-sets/{set_id}",
    summary="Набор практики по id",
    description="Публичный набор практики (например, для mock-интервью).",
)
async def get_set(
    set_id: uuid.UUID, _: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> PracticeSetOut:
    return set_out(await service.get_set(set_id))


@router.post(
    "/practice-sets/{set_id}/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Начать тренировку по набору",
    description="Создаёт сессию прохождения указанного набора практики.",
)
async def start_session(
    set_id: uuid.UUID, user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> PracticeSessionOut:
    return PracticeSessionOut.model_validate(await service.start_session(set_id, user.id))


@router.get(
    "/practice-sessions/{session_id}",
    summary="Сессия тренировки по id",
    description="Статус и решённые задачи текущей сессии практики.",
)
async def get_session(
    session_id: uuid.UUID, user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> PracticeSessionOut:
    return PracticeSessionOut.model_validate(await service.get_session(session_id, user.id))


@router.post(
    "/practice-sessions/{session_id}/complete",
    summary="Завершить сессию тренировки",
    description="Закрывает сессию и сохраняет итоговую рефлексию по ней.",
)
async def complete_session(
    session_id: uuid.UUID,
    payload: CompleteSession,
    user: CurrentUser,
    service: FromDishka[AlgorithmPracticeService],
) -> PracticeSessionOut:
    return PracticeSessionOut.model_validate(
        await service.complete_session(session_id, user.id, payload.reflection_md)
    )


@router.get(
    "/algorithms/problems/{problem_id}",
    summary="Алгоритмическая задача по id",
    description="Условие опубликованной задачи для решения в тренажёре.",
)
async def get_problem(
    problem_id: uuid.UUID, _: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> ProblemOut:
    return problem_out(await service.get_problem(problem_id))


@router.get(
    "/algorithms/languages",
    summary="Доступные языки для решения задач",
    description="Языки, которые сейчас может запускать исполнитель кода.",
)
async def languages(_: CurrentUser, runner: FromDishka[CodeRunner]) -> list[RunnerLanguageOut]:
    return [RunnerLanguageOut.model_validate(language) for language in await runner.languages()]


@router.post(
    "/algorithms/problems/{problem_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить код на кастомном вводе",
    description="Ставит запуск в очередь исполнителя; результат не засчитывается как решение.",
)
async def run_code(
    problem_id: uuid.UUID,
    payload: RunCreate,
    user: CurrentUser,
    service: FromDishka[AlgorithmPracticeService],
) -> SubmissionOut:
    submission = await service.enqueue(
        payload.session_id,
        problem_id,
        user.id,
        SubmissionKind.RUN,
        payload.language,
        payload.source_code,
        payload.custom_input,
    )
    return submission_out(submission)


@router.post(
    "/algorithms/problems/{problem_id}/submissions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Отправить решение на проверку",
    description="Ставит посылку в очередь исполнителя; засчитывается как попытка решения.",
)
async def submit_code(
    problem_id: uuid.UUID,
    payload: SubmissionCreate,
    user: CurrentUser,
    service: FromDishka[AlgorithmPracticeService],
) -> SubmissionOut:
    submission = await service.enqueue(
        payload.session_id,
        problem_id,
        user.id,
        SubmissionKind.SUBMIT,
        payload.language,
        payload.source_code,
    )
    return submission_out(submission)


@router.get(
    "/algorithms/submissions/{submission_id}",
    summary="Статус запуска или посылки",
    description="Опрашивается пока запуск/посылка не завершится (статус, вывод, вердикт).",
)
async def get_submission(
    submission_id: uuid.UUID, user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> SubmissionOut:
    return submission_out(await service.get_submission(submission_id, user.id))


@router.get(
    "/algorithms/problems/{problem_id}/progress",
    summary="Прогресс по задаче",
    description="Статус решения задачи и рефлексия текущего пользователя.",
)
async def get_progress(
    problem_id: uuid.UUID, user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> ProgressOut:
    return ProgressOut.model_validate(await service.get_progress(problem_id, user.id))


@router.get(
    "/algorithms/problems/{problem_id}/solutions",
    summary="Принятые решения по задаче",
    description="Все принятые посылки текущего пользователя, от новых к старым.",
)
async def list_solutions(
    problem_id: uuid.UUID, user: CurrentUser, service: FromDishka[AlgorithmPracticeService]
) -> list[SolutionOut]:
    solutions = await service.list_solutions(problem_id, user.id)
    return [solution_out(solution) for solution in solutions]


@router.put(
    "/algorithms/problems/{problem_id}/reflection",
    summary="Сохранить рефлексию по задаче",
    description="Заметки о сложности решения, уверенности и разборе задачи.",
)
async def update_reflection(
    problem_id: uuid.UUID,
    payload: ReflectionUpdate,
    user: CurrentUser,
    service: FromDishka[AlgorithmPracticeService],
) -> ProgressOut:
    return ProgressOut.model_validate(
        await service.update_reflection(
            problem_id, user.id, payload.complexity_md, payload.confidence, payload.reflection_md
        )
    )
