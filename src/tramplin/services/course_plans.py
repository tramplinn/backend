from __future__ import annotations

from collections import Counter

import uuid_utils.compat as uuid
from anyio import to_thread

from tramplin.core.errors import InvalidLessonContentError, InvalidQuizError, NotFoundError
from tramplin.models.algorithms import PracticeSet, PracticeSetProblem
from tramplin.models.assets import Asset
from tramplin.models.content import Course, InterviewCard, Lesson, Module, ModuleItem
from tramplin.models.enums import ContentStatus, PracticeMode, QuestionType
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.algorithm_ports import AlgorithmAuthoringRepositoryPort
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.course_plan_schemas import (
    CoursePlanApply,
    CoursePlanModule,
    CoursePlanPracticeSet,
    CoursePlanQuestion,
)
from tramplin.services.courses import CourseRepositoryPort
from tramplin.services.entity_updates import require
from tramplin.services.lesson_markdown import render_lesson_content
from tramplin.services.lessons import LessonRepositoryPort
from tramplin.services.modules import ModuleRepositoryPort
from tramplin.services.plan_report import PlanChange, PlanReport
from tramplin.services.quizzes import QuizRepositoryPort, validate_question

ADDITIVE_WARNING = "Additive-only: сущности вне плана сохраняются и уходят в конец списка."


class CoursePlanService:
    """Применяет весь план одной транзакцией; ошибка откатывает план целиком.

    preview прогоняет тот же код без commit: сессия запроса откатывает его при закрытии,
    поэтому diff предпросмотра совпадает с тем, что сделает apply.
    """

    def __init__(
        self,
        transaction: Transaction,
        courses: CourseRepositoryPort,
        modules: ModuleRepositoryPort,
        lessons: LessonRepositoryPort,
        quizzes: QuizRepositoryPort,
        assets: AssetRepositoryPort,
        algorithms: AlgorithmAuthoringRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._courses = courses
        self._modules = modules
        self._lessons = lessons
        self._quizzes = quizzes
        self._assets = assets
        self._algorithms = algorithms

    async def validate(self, plan: CoursePlanApply) -> PlanReport:
        report = PlanReport()
        for module_plan in plan.modules:
            await self._validate_module(f"{plan.slug}/{module_plan.slug}", module_plan, report)
        return report

    async def preview(self, plan: CoursePlanApply, actor_id: uuid.UUID) -> PlanReport:
        report = await self.validate(plan)
        if report.valid:
            await self._apply(plan, actor_id, report)
            await self._transaction.flush()
        return report

    async def apply(self, plan: CoursePlanApply, actor_id: uuid.UUID) -> tuple[Course, PlanReport]:
        report = await self.validate(plan)
        report.raise_if_invalid()
        course = await self._apply(plan, actor_id, report)
        await self._transaction.commit()
        return course, report

    async def preview_practice_set(
        self,
        course_slug: str,
        module_slug: str,
        plan: CoursePlanPracticeSet,
        actor_id: uuid.UUID,
    ) -> PlanReport:
        module = await self._target_module(course_slug, module_slug)
        path = f"{course_slug}/{module_slug}/practice/{plan.title}"
        report = PlanReport()
        await self._validate_practice_set(path, plan, report)
        if report.valid:
            await self._apply_practice_set(module, path, plan, actor_id, report)
            await self._transaction.flush()
        return report

    async def apply_practice_set(
        self,
        course_slug: str,
        module_slug: str,
        plan: CoursePlanPracticeSet,
        actor_id: uuid.UUID,
    ) -> PlanReport:
        """Создаёт/обновляет один набор практики, не трогая остальной курс и порядок модуля."""
        module = await self._target_module(course_slug, module_slug)
        path = f"{course_slug}/{module_slug}/practice/{plan.title}"
        report = PlanReport()
        await self._validate_practice_set(path, plan, report)
        report.raise_if_invalid()
        await self._apply_practice_set(module, path, plan, actor_id, report)
        await self._transaction.commit()
        return report

    async def _target_module(self, course_slug: str, module_slug: str) -> Module:
        course = require(
            await self._courses.get_by_slug(course_slug, published_only=False),
            NotFoundError(f"Курс '{course_slug}' не найден", slug=course_slug),
        )
        return require(
            next((module for module in course.modules if module.slug == module_slug), None),
            NotFoundError(
                f"Модуль '{module_slug}' не найден в курсе '{course_slug}'", slug=module_slug
            ),
        )

    async def _validate_module(self, path: str, plan: CoursePlanModule, report: PlanReport) -> None:
        lesson_slugs = {lesson.slug for lesson in plan.lessons}
        for lesson_plan in plan.lessons:
            lesson_path = f"{path}/{lesson_plan.slug}"
            if not lesson_plan.body_md.strip():
                report.warning(lesson_path, "empty_lesson", "Пустой урок")
                continue
            try:
                await to_thread.run_sync(render_lesson_content, lesson_plan.body_md)
            except InvalidLessonContentError as error:
                line = error.details.get("line")
                suffix = f" (строка {line})" if line is not None else ""
                report.error(lesson_path, "invalid_markdown", f"{error.message}{suffix}")

        for quiz_plan in plan.quizzes:
            quiz_path = f"{path}/{quiz_plan.slug}"
            if quiz_plan.lesson_slug and quiz_plan.lesson_slug not in lesson_slugs:
                report.error(
                    quiz_path,
                    "unknown_lesson",
                    f"lesson_slug '{quiz_plan.lesson_slug}' должен ссылаться на урок "
                    "из того же модуля этого плана",
                )
            if not quiz_plan.questions:
                report.warning(quiz_path, "empty_quiz", "Тест без вопросов")
            positions = Counter(question.position for question in quiz_plan.questions)
            for position, count in positions.items():
                if count > 1:
                    report.error(
                        f"{quiz_path}/questions/{position}",
                        "duplicate_question_position",
                        "position вопроса должен быть уникальным внутри теста",
                    )
            for question in quiz_plan.questions:
                await self._validate_question(
                    f"{quiz_path}/questions/{question.position}", question, report
                )

        for practice_plan in plan.practice_sets:
            await self._validate_practice_set(
                f"{path}/practice/{practice_plan.title}", practice_plan, report
            )

    async def _validate_question(
        self, path: str, plan: CoursePlanQuestion, report: PlanReport
    ) -> None:
        try:
            validate_question(QuestionType(plan.type), plan.options, plan.answer)
        except InvalidQuizError as error:
            report.error(path, "invalid_question", error.message)
        if len(plan.attachment_ids) != len(set(plan.attachment_ids)):
            report.error(path, "duplicate_attachment", "Прикреплённые файлы не должны повторяться")
        for asset_id in dict.fromkeys(plan.attachment_ids):
            if await self._assets.get(asset_id) is None:
                report.error(path, "unknown_attachment", f"Прикреплённый файл {asset_id} не найден")

    async def _validate_practice_set(
        self, path: str, plan: CoursePlanPracticeSet, report: PlanReport
    ) -> None:
        if not plan.problem_slugs:
            report.warning(path, "empty_practice_set", "Набор практики без задач")
        if len(plan.problem_slugs) != len(set(plan.problem_slugs)):
            report.error(path, "duplicate_problem", "Задача не может повторяться в наборе")
        if plan.mode == "mock_interview" and plan.duration_minutes is None:
            report.warning(
                path,
                "missing_duration",
                "Для mock_interview нужен duration_minutes, иначе набор не опубликовать",
            )
        for slug in dict.fromkeys(plan.problem_slugs):
            if await self._algorithms.get_problem_by_slug(slug) is None:
                report.error(
                    path,
                    "unknown_problem",
                    f"Задачи '{slug}' нет в банке: создайте её через план банка задач",
                )

    async def _apply(
        self, plan: CoursePlanApply, actor_id: uuid.UUID, report: PlanReport
    ) -> Course:
        course = await self._courses.get_by_slug(plan.slug, published_only=False)
        if course is None:
            course = Course(
                title=plan.title,
                slug=plan.slug,
                summary=plan.summary,
                color=plan.color,
                est_hours=plan.est_hours,
                cover_asset_id=None,
                status=ContentStatus.DRAFT,
            )
            course.modules = []
            report.create("course", plan.slug, course, actor_id)
            self._courses.add(course)
        else:
            report.warnings.append(ADDITIVE_WARNING)
            report.update(
                "course",
                plan.slug,
                course,
                {
                    "title": plan.title,
                    "summary": plan.summary,
                    "color": plan.color,
                    "est_hours": plan.est_hours,
                    "status": ContentStatus.DRAFT,
                },
                actor_id,
            )

        modules = {module.slug: module for module in course.modules}
        desired_slugs = {module_plan.slug for module_plan in plan.modules}
        preserved_modules = [
            module for module in course.modules if module.slug not in desired_slugs
        ]
        # Сначала уводим модули вне плана во временный отрицательный диапазон и
        # сбрасываем на диск: позиции гарантированно попарно различны и не пересекаются
        # ни с чем существующим, поэтому не зависят от порядка, в котором SQLAlchemy
        # отправит сами UPDATE. Без этого шага INSERT нового модуля на позицию,
        # которую ещё держит несдвинутый старый, падает на uq_modules_course_id_position
        # (а сдвиг всех разом одним шагом в финальные позиции упёрся бы в то же самое
        # ограничение между собой, если модулей вне плана больше одного).
        for offset, preserved_module in enumerate(preserved_modules):
            preserved_module.position = -(offset + 1)
        if preserved_modules:
            await self._transaction.flush()

        desired_modules: list[Module] = []
        for position, module_plan in enumerate(plan.modules):
            path = f"{plan.slug}/{module_plan.slug}"
            module = modules.get(module_plan.slug)
            if module is None:
                module = Module(
                    course_id=course.id,
                    title=module_plan.title,
                    slug=module_plan.slug,
                    summary=module_plan.summary,
                    position=position,
                    status=ContentStatus.DRAFT,
                )
                module.items = []
                change = report.create("module", path, module, actor_id)
                self._modules.add(module)
            else:
                change = report.update(
                    "module",
                    path,
                    module,
                    {
                        "title": module_plan.title,
                        "summary": module_plan.summary,
                        "position": position,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                )
            desired_modules.append(module)
            await self._apply_module(module, path, module_plan, change, actor_id, report)

        ordered_modules = [*desired_modules, *preserved_modules]
        for position, module in enumerate(ordered_modules):
            module.position = position
        return course

    async def _apply_module(
        self,
        module: Module,
        path: str,
        plan: CoursePlanModule,
        change: PlanChange,
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> None:
        order_before = [item.id for item in sorted(module.items, key=lambda item: item.position)]
        existing_lessons = {
            item.lesson.slug: item.lesson for item in module.items if item.lesson is not None
        }
        existing_quizzes = {
            item.quiz.slug: item.quiz for item in module.items if item.quiz is not None
        }
        lessons: dict[str, Lesson] = {}
        item_by_slug: dict[str, ModuleItem] = {}
        for lesson_plan in plan.lessons:
            lesson_path = f"{path}/{lesson_plan.slug}"
            lesson = existing_lessons.get(lesson_plan.slug)
            if lesson is None:
                lesson = Lesson(
                    module_id=module.id,
                    title=lesson_plan.title,
                    slug=lesson_plan.slug,
                    est_minutes=lesson_plan.est_minutes,
                    body_md=lesson_plan.body_md,
                    body_html="",
                    status=ContentStatus.DRAFT,
                )
                lesson.interview_cards = []
                report.create("lesson", lesson_path, lesson, actor_id)
                self._lessons.add(lesson)
                # ModuleItem.lesson — viewonly, ORM не строит по нему порядок flush: без явного
                # flush тут INSERT INTO module_items мог уйти раньше INSERT INTO lessons и
                # упасть на fk_module_items_lesson_id_module_id_lessons.
                await self._transaction.flush()
                item = self._new_item(module, actor_id, lesson_id=lesson.id)
            else:
                lesson = await self._lessons.get_with_interview_cards(lesson.id) or lesson
                report.update(
                    "lesson",
                    lesson_path,
                    lesson,
                    {
                        "title": lesson_plan.title,
                        "est_minutes": lesson_plan.est_minutes,
                        "body_md": lesson_plan.body_md,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                )
                item = next(item for item in module.items if item.lesson_id == lesson.id)
            await self._render_lesson(lesson, actor_id)
            lessons[lesson.slug] = lesson
            item_by_slug[lesson.slug] = item

        for quiz_plan in plan.quizzes:
            quiz_path = f"{path}/{quiz_plan.slug}"
            lesson = lessons.get(quiz_plan.lesson_slug or "")
            quiz = existing_quizzes.get(quiz_plan.slug)
            if quiz is None:
                quiz = Quiz(
                    module_id=module.id,
                    lesson_id=lesson.id if lesson else None,
                    title=quiz_plan.title,
                    slug=quiz_plan.slug,
                    status=ContentStatus.DRAFT,
                )
                quiz.questions = []
                report.create("quiz", quiz_path, quiz, actor_id)
                self._quizzes.add(quiz)
                # ModuleItem.quiz — viewonly, ORM не строит по нему порядок flush: без явного
                # flush тут INSERT INTO module_items мог уйти раньше INSERT INTO quizzes и
                # упасть на fk_module_items_quiz_id_module_id_quizzes.
                await self._transaction.flush()
                item = self._new_item(module, actor_id, quiz_id=quiz.id)
            else:
                report.update(
                    "quiz",
                    quiz_path,
                    quiz,
                    {
                        "title": quiz_plan.title,
                        "lesson_id": lesson.id if lesson else None,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                )
                item = next(item for item in module.items if item.quiz_id == quiz.id)
            await self._apply_questions(quiz, quiz_path, quiz_plan.questions, actor_id, report)
            item_by_slug[quiz.slug] = item

        for practice_plan in plan.practice_sets:
            item_by_slug[practice_plan.title] = await self._apply_practice_set(
                module, f"{path}/practice/{practice_plan.title}", practice_plan, actor_id, report
            )

        desired_slugs = plan.content_order or [
            *lessons,
            *(quiz.slug for quiz in plan.quizzes),
            *(practice.title for practice in plan.practice_sets),
        ]
        desired_items = [item_by_slug[slug] for slug in desired_slugs]
        desired_ids = {item.id for item in desired_items}
        preserved_items = [item for item in module.items if item.id not in desired_ids]
        ordered_items = [*desired_items, *preserved_items]
        for position, item in enumerate(ordered_items):
            item.position = position
            item.updated_by = actor_id
        existing_ids = set(order_before)
        if [item.id for item in ordered_items if item.id in existing_ids] != order_before:
            change.touch("content_order")

    async def _apply_practice_set(
        self,
        module: Module,
        path: str,
        plan: CoursePlanPracticeSet,
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> ModuleItem:
        problem_ids = [
            require(
                await self._algorithms.get_problem_by_slug(slug),
                NotFoundError(f"Задача '{slug}' не найдена"),
            ).id
            for slug in plan.problem_slugs
        ]
        existing = next(
            (
                item.practice_set
                for item in module.items
                if item.practice_set is not None and item.practice_set.title == plan.title
            ),
            None,
        )
        if existing is None:
            practice_set = PracticeSet(
                title=plan.title,
                description=plan.description,
                mode=PracticeMode(plan.mode),
                duration_minutes=plan.duration_minutes,
                status=ContentStatus.DRAFT,
            )
            practice_set.problems = []
            change = report.create("practice", path, practice_set, actor_id)
            self._algorithms.add_set(practice_set)
            # ModuleItem.practice_set — viewonly, ORM не строит по нему порядок flush: без
            # явного flush тут INSERT INTO module_items мог уйти раньше INSERT INTO
            # practice_sets и упасть на FK-ограничении.
            await self._transaction.flush()
            item = self._new_item(module, actor_id, practice_set_id=practice_set.id)
        else:
            loaded = await self._algorithms.get_set(existing.id, published_only=False)
            practice_set = loaded or existing
            change = report.update(
                "practice",
                path,
                practice_set,
                {
                    "title": plan.title,
                    "description": plan.description,
                    "mode": PracticeMode(plan.mode),
                    "duration_minutes": plan.duration_minutes,
                },
                actor_id,
            )
            item = next(item for item in module.items if item.practice_set_id == practice_set.id)
        if await self._apply_practice_problems(practice_set, problem_ids, actor_id):
            change.touch("problem_slugs")
        return item

    async def _apply_questions(
        self,
        quiz: Quiz,
        path: str,
        plans: list[CoursePlanQuestion],
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> None:
        existing = {question.position: question for question in quiz.questions}
        for plan in plans:
            question_path = f"{path}/questions/{plan.position}"
            attachments = await self._assets_for(plan.attachment_ids)
            question = existing.get(plan.position)
            values: dict[str, object] = {
                "position": plan.position,
                "prompt_md": plan.prompt_md,
                "type": QuestionType(plan.type),
                "options_json": plan.options,
                "answer_json": plan.answer,
                "explain_md": plan.explain_md,
            }
            if question is None:
                question = QuizQuestion(quiz_id=quiz.id, **values)
                question.attachments = attachments
                report.create("question", question_path, question, actor_id)
                self._quizzes.add_question(question)
                quiz.questions.append(question)
            else:
                values["attachments"] = attachments
                report.update("question", question_path, question, values, actor_id)

    async def _apply_practice_problems(
        self,
        practice_set: PracticeSet,
        problem_ids: list[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> bool:
        """Возвращает True, если состав или порядок задач набора изменился."""
        order_before = [
            item.problem_id for item in sorted(practice_set.problems, key=lambda i: i.position)
        ]
        existing = {item.problem_id: item for item in practice_set.problems}
        desired_ids = set(problem_ids)
        preserved = [item for item in practice_set.problems if item.problem_id not in desired_ids]
        # Тот же трюк, что и с модулями: сначала уводим задачи вне плана во временный
        # отрицательный диапазон, чтобы финальная расстановка позиций не столкнулась с
        # uq на (practice_set_id, position).
        for offset, item in enumerate(preserved):
            item.position = -(offset + 1)
        if preserved:
            await self._transaction.flush()
        desired_items: list[PracticeSetProblem] = []
        for problem_id in problem_ids:
            found = existing.get(problem_id)
            if found is None:
                found = PracticeSetProblem(
                    practice_set_id=practice_set.id,
                    problem_id=problem_id,
                    position=len(desired_items),
                    recommended_minutes=None,
                    created_by=actor_id,
                )
                self._algorithms.add_set_problem(found)
                practice_set.problems.append(found)
            desired_items.append(found)
        ordered = [*desired_items, *preserved]
        for position, item in enumerate(ordered):
            item.position = position
            item.updated_by = actor_id
        return [item.problem_id for item in ordered] != order_before

    async def _render_lesson(self, lesson: Lesson, actor_id: uuid.UUID) -> None:
        rendered = await to_thread.run_sync(render_lesson_content, lesson.body_md)
        lesson.body_html = rendered.body_html
        lesson.interview_cards = [
            InterviewCard(
                lesson_id=lesson.id,
                position=card.position,
                question_md=card.question_md,
                answer_md=card.answer_md,
                created_by=actor_id,
                updated_by=actor_id,
            )
            for card in rendered.interview_cards
        ]

    async def _assets_for(self, ids: list[uuid.UUID]) -> list[Asset]:
        if len(ids) != len(set(ids)):
            raise InvalidQuizError("Прикреплённые файлы не должны повторяться")
        result: list[Asset] = []
        for asset_id in ids:
            asset = require(
                await self._assets.get(asset_id), NotFoundError("Прикреплённый файл не найден")
            )
            result.append(asset)
        return result

    def _new_item(
        self,
        module: Module,
        actor_id: uuid.UUID,
        *,
        lesson_id: uuid.UUID | None = None,
        quiz_id: uuid.UUID | None = None,
        practice_set_id: uuid.UUID | None = None,
    ) -> ModuleItem:
        item = ModuleItem(
            module_id=module.id,
            position=len(module.items),
            lesson_id=lesson_id,
            quiz_id=quiz_id,
            practice_set_id=practice_set_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._modules.add_item(item)
        module.items.append(item)
        return item
