from __future__ import annotations

from dataclasses import dataclass

import uuid_utils.compat as uuid
from anyio import to_thread

from tramplin.api.schemas.course_plans import (
    CoursePlanApply,
    CoursePlanModule,
    CoursePlanQuestion,
)
from tramplin.core.errors import InvalidQuizError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.content import Course, InterviewCard, Lesson, Module, ModuleItem
from tramplin.models.enums import ContentStatus, QuestionType
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.courses import CourseRepositoryPort
from tramplin.services.entity_updates import mark_created, mark_updated
from tramplin.services.lesson_markdown import render_lesson_content
from tramplin.services.lessons import LessonRepositoryPort
from tramplin.services.modules import ModuleRepositoryPort
from tramplin.services.quizzes import QuizRepositoryPort, validate_question


@dataclass(slots=True)
class ApplyStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


class CoursePlanService:
    """Применяет весь план одной транзакцией; ошибка откатывает план целиком."""

    def __init__(
        self,
        transaction: Transaction,
        courses: CourseRepositoryPort,
        modules: ModuleRepositoryPort,
        lessons: LessonRepositoryPort,
        quizzes: QuizRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._courses = courses
        self._modules = modules
        self._lessons = lessons
        self._quizzes = quizzes
        self._assets = assets

    async def apply(self, plan: CoursePlanApply, actor_id: uuid.UUID) -> tuple[Course, ApplyStats]:
        stats = ApplyStats()
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
            mark_created(course, actor_id)
            self._courses.add(course)
            stats.created += 1
        else:
            self._update(
                course,
                {
                    "title": plan.title,
                    "summary": plan.summary,
                    "color": plan.color,
                    "est_hours": plan.est_hours,
                    "status": ContentStatus.DRAFT,
                },
                actor_id,
                stats,
            )

        modules = {module.slug: module for module in course.modules}
        desired_modules: list[Module] = []
        for position, module_plan in enumerate(plan.modules):
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
                mark_created(module, actor_id)
                self._modules.add(module)
                stats.created += 1
            else:
                self._update(
                    module,
                    {
                        "title": module_plan.title,
                        "summary": module_plan.summary,
                        "position": position,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                    stats,
                )
            desired_modules.append(module)
            await self._apply_module(module, module_plan, actor_id, stats)

        desired_slugs = {module.slug for module in desired_modules}
        preserved_modules = [
            module for module in course.modules if module.slug not in desired_slugs
        ]
        ordered_modules = [*desired_modules, *preserved_modules]
        for position, module in enumerate(ordered_modules):
            module.position = position
        await self._transaction.commit()
        return course, stats

    async def _apply_module(
        self,
        module: Module,
        plan: CoursePlanModule,
        actor_id: uuid.UUID,
        stats: ApplyStats,
    ) -> None:
        lesson_plans = plan.lessons
        quiz_plans = plan.quizzes
        existing_lessons = {
            item.lesson.slug: item.lesson for item in module.items if item.lesson is not None
        }
        existing_quizzes = {
            item.quiz.slug: item.quiz for item in module.items if item.quiz is not None
        }
        lessons: dict[str, Lesson] = {}
        item_by_slug: dict[str, ModuleItem] = {}
        for lesson_plan in lesson_plans:
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
                mark_created(lesson, actor_id)
                self._lessons.add(lesson)
                item = self._new_item(module, actor_id, lesson_id=lesson.id)
                stats.created += 1
            else:
                lesson = await self._lessons.get_with_interview_cards(lesson.id) or lesson
                self._update(
                    lesson,
                    {
                        "title": lesson_plan.title,
                        "est_minutes": lesson_plan.est_minutes,
                        "body_md": lesson_plan.body_md,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                    stats,
                )
                item = next(item for item in module.items if item.lesson_id == lesson.id)
            await self._render_lesson(lesson, actor_id)
            lessons[lesson.slug] = lesson
            item_by_slug[lesson.slug] = item

        for quiz_plan in quiz_plans:
            lesson = lessons.get(quiz_plan.lesson_slug or "")
            if quiz_plan.lesson_slug and lesson is None:
                raise InvalidQuizError("lesson_slug теста должен ссылаться на урок того же модуля")
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
                mark_created(quiz, actor_id)
                self._quizzes.add(quiz)
                item = self._new_item(module, actor_id, quiz_id=quiz.id)
                stats.created += 1
            else:
                self._update(
                    quiz,
                    {
                        "title": quiz_plan.title,
                        "lesson_id": lesson.id if lesson else None,
                        "status": ContentStatus.DRAFT,
                    },
                    actor_id,
                    stats,
                )
                item = next(item for item in module.items if item.quiz_id == quiz.id)
            await self._apply_questions(quiz, quiz_plan.questions, actor_id, stats)
            item_by_slug[quiz.slug] = item

        desired_slugs = plan.content_order or [*lessons, *(quiz.slug for quiz in quiz_plans)]
        desired_items = [item_by_slug[slug] for slug in desired_slugs]
        desired_ids = {item.id for item in desired_items}
        preserved_items = [item for item in module.items if item.id not in desired_ids]
        ordered_items = [*desired_items, *preserved_items]
        for position, item in enumerate(ordered_items):
            item.position = position
            item.updated_by = actor_id

    async def _apply_questions(
        self,
        quiz: Quiz,
        plans: list[CoursePlanQuestion],
        actor_id: uuid.UUID,
        stats: ApplyStats,
    ) -> None:
        existing = {question.position: question for question in quiz.questions}
        for plan in plans:
            question_type = QuestionType(plan.type)
            validate_question(question_type, plan.options, plan.answer)
            attachments = await self._assets_for(plan.attachment_ids)
            question = existing.get(plan.position)
            values = {
                "position": plan.position,
                "prompt_md": plan.prompt_md,
                "type": question_type,
                "options_json": plan.options,
                "answer_json": plan.answer,
                "explain_md": plan.explain_md,
            }
            if question is None:
                question = QuizQuestion(quiz_id=quiz.id, **values)
                question.attachments = attachments
                mark_created(question, actor_id)
                self._quizzes.add_question(question)
                quiz.questions.append(question)
                stats.created += 1
            else:
                values["attachments"] = attachments
                self._update(question, values, actor_id, stats)

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
            asset = await self._assets.get(asset_id)
            if asset is None:
                raise NotFoundError("Прикреплённый файл не найден")
            result.append(asset)
        return result

    def _new_item(
        self,
        module: Module,
        actor_id: uuid.UUID,
        *,
        lesson_id: uuid.UUID | None = None,
        quiz_id: uuid.UUID | None = None,
    ) -> ModuleItem:
        item = ModuleItem(
            module_id=module.id,
            position=len(module.items),
            lesson_id=lesson_id,
            quiz_id=quiz_id,
            practice_set_id=None,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._modules.add_item(item)
        module.items.append(item)
        return item

    @staticmethod
    def _update(
        entity: Course | Module | Lesson | Quiz | QuizQuestion,
        values: dict[str, object],
        actor_id: uuid.UUID,
        stats: ApplyStats,
    ) -> None:
        changed = False
        for field, value in values.items():
            if getattr(entity, field) != value:
                setattr(entity, field, value)
                changed = True
        if changed:
            mark_updated(entity, actor_id)
            stats.updated += 1
        else:
            stats.unchanged += 1
