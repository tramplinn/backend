import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.algorithm_mapping import problem_author_out, set_out
from tramplin.api.dependencies import TeacherUser
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
from tramplin.models.algorithms import AlgorithmProblem, AlgorithmTestCase, PracticeSet
from tramplin.services.algorithms import AlgorithmAuthoringService

router = APIRouter(tags=["authoring:algorithms"], route_class=DishkaRoute)


@router.get("/algorithms/problems")
async def list_problems(
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> list[ProblemAuthorOut]:
    return [problem_author_out(item) for item in await service.list_problems()]


@router.post("/algorithms/problems", status_code=status.HTTP_201_CREATED)
async def create_problem(
    payload: ProblemCreate, user: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> ProblemAuthorOut:
    data = payload.model_dump()
    data["external_url"] = str(data["external_url"]) if data["external_url"] else None
    tag_names = data.pop("tags")
    problem = AlgorithmProblem(statement_html="", **data)
    return problem_author_out(await service.create_problem(problem, tag_names, user.id))


@router.get("/algorithms/problems/{problem_id}")
async def get_problem(
    problem_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> ProblemAuthorOut:
    return problem_author_out(await service.get_problem(problem_id))


@router.patch("/algorithms/problems/{problem_id}")
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


@router.delete("/algorithms/problems/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_problem(
    problem_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> None:
    await service.delete_problem(problem_id)


@router.post("/algorithms/problems/{problem_id}/test-cases", status_code=status.HTTP_201_CREATED)
async def add_case(
    problem_id: uuid.UUID,
    payload: TestCaseCreate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TestCaseOut:
    case = AlgorithmTestCase(problem_id=problem_id, **payload.model_dump())
    return TestCaseOut.model_validate(await service.add_case(problem_id, case, user.id))


@router.patch("/algorithms/test-cases/{case_id}")
async def update_case(
    case_id: uuid.UUID,
    payload: TestCaseUpdate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> TestCaseOut:
    return TestCaseOut.model_validate(
        await service.update_case(case_id, payload.model_dump(exclude_unset=True), user.id)
    )


@router.delete("/algorithms/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> None:
    await service.delete_case(case_id)


@router.put("/algorithms/problems/{problem_id}/templates/{language}")
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


@router.post("/algorithms/problems/{problem_id}/templates/{language}/validate")
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
)
async def delete_template(
    problem_id: uuid.UUID,
    language: str,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.delete_template(problem_id, language)


@router.post("/modules/{module_id}/practice-sets", status_code=status.HTTP_201_CREATED)
async def create_set(
    module_id: uuid.UUID,
    payload: PracticeSetCreate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    return set_out(
        await service.create_set(module_id, PracticeSet(**payload.model_dump()), user.id)
    )


@router.get("/practice-sets/{set_id}")
async def get_set(
    set_id: uuid.UUID, _: TeacherUser, service: FromDishka[AlgorithmAuthoringService]
) -> PracticeSetOut:
    return set_out(await service.get_set(set_id))


@router.get("/practice-sets")
async def list_sets(
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> list[PracticeSetOut]:
    return [set_out(item) for item in await service.list_sets()]


@router.patch("/practice-sets/{set_id}")
async def update_set(
    set_id: uuid.UUID,
    payload: PracticeSetUpdate,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    return set_out(
        await service.update_set(set_id, payload.model_dump(exclude_unset=True), user.id)
    )


@router.delete("/practice-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_set(
    set_id: uuid.UUID,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.delete_set(set_id)


@router.post("/practice-sets/{set_id}/problems", status_code=status.HTTP_201_CREATED)
async def add_set_problem(
    set_id: uuid.UUID,
    payload: SetProblemAdd,
    user: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> PracticeSetOut:
    await service.add_set_problem(set_id, payload.problem_id, payload.recommended_minutes, user.id)
    return set_out(await service.get_set(set_id))


@router.put("/practice-sets/{set_id}/problems/order", status_code=status.HTTP_204_NO_CONTENT)
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
)
async def remove_set_problem(
    set_id: uuid.UUID,
    problem_id: uuid.UUID,
    _: TeacherUser,
    service: FromDishka[AlgorithmAuthoringService],
) -> None:
    await service.remove_set_problem(set_id, problem_id)
