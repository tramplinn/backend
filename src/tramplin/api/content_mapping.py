from tramplin.api.schemas.assets import AssetOut
from tramplin.api.schemas.courses import CourseOut, CourseTreeOut
from tramplin.api.schemas.lessons import LessonOut
from tramplin.api.schemas.modules import (
    LessonModuleItemOut,
    ModuleTreeOut,
    PracticeModuleItemOut,
    PracticeSetModuleSummary,
    QuizModuleItemOut,
)
from tramplin.api.schemas.quizzes import (
    QuizAuthorOut,
    QuizOut,
    QuizQuestionAuthorOut,
    QuizQuestionOut,
)
from tramplin.api.schemas.tracks import TrackCourseOut, TrackOut
from tramplin.models.assets import Asset
from tramplin.models.content import Course, Lesson, Module, Track
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


def course_out(course: Course, *, asset_base_url: str) -> CourseOut:
    return CourseOut(
        id=course.id,
        title=course.title,
        slug=course.slug,
        summary=course.summary,
        color=course.color,
        est_hours=course.est_hours,
        cover_asset_id=course.cover_asset_id,
        cover_url=(
            f"{asset_base_url}/{course.cover_asset.s3_key}"
            if course.cover_asset is not None
            else None
        ),
        status=course.status,
    )


def track_out(track: Track, *, published_only: bool, asset_base_url: str) -> TrackOut:
    links = sorted(track.courses, key=lambda item: item.position)
    if published_only:
        links = [link for link in links if link.course.status is ContentStatus.PUBLISHED]
    return TrackOut(
        id=track.id,
        title=track.title,
        slug=track.slug,
        description=track.description,
        color=track.color,
        status=track.status,
        courses=[
            TrackCourseOut(
                position=link.position,
                course=course_out(link.course, asset_base_url=asset_base_url),
            )
            for link in links
        ],
    )


def lesson_out(lesson: Lesson) -> LessonOut:
    return LessonOut.model_validate(lesson)


def asset_out(asset: Asset, *, asset_base_url: str) -> AssetOut:
    return AssetOut(
        id=asset.id,
        filename=asset.filename,
        mime=asset.mime,
        size=asset.size,
        url=f"{asset_base_url}/{asset.s3_key}",
    )


def question_out(question: QuizQuestion, *, asset_base_url: str) -> QuizQuestionOut:
    return QuizQuestionOut(
        id=question.id,
        position=question.position,
        prompt_md=question.prompt_md,
        type=question.type,
        options=question.options_json,
        attachments=[
            asset_out(asset, asset_base_url=asset_base_url) for asset in question.attachments
        ],
    )


def question_author_out(
    question: QuizQuestion,
    *,
    asset_base_url: str,
) -> QuizQuestionAuthorOut:
    return QuizQuestionAuthorOut(
        **question_out(question, asset_base_url=asset_base_url).model_dump(),
        answer=question.answer_json,
        explain_md=question.explain_md,
    )


def quiz_out(quiz: Quiz, *, asset_base_url: str) -> QuizOut:
    questions = sorted(quiz.questions, key=lambda item: item.position)
    return QuizOut(
        id=quiz.id,
        module_id=quiz.module_id,
        lesson_id=quiz.lesson_id,
        title=quiz.title,
        slug=quiz.slug,
        status=quiz.status,
        questions=[question_out(question, asset_base_url=asset_base_url) for question in questions],
    )


def quiz_author_out(quiz: Quiz, *, asset_base_url: str) -> QuizAuthorOut:
    questions = sorted(quiz.questions, key=lambda item: item.position)
    return QuizAuthorOut(
        id=quiz.id,
        module_id=quiz.module_id,
        lesson_id=quiz.lesson_id,
        title=quiz.title,
        slug=quiz.slug,
        status=quiz.status,
        questions=[
            question_author_out(question, asset_base_url=asset_base_url) for question in questions
        ],
    )


def module_tree_out(
    module: Module,
    *,
    published_only: bool,
    asset_base_url: str,
) -> ModuleTreeOut:
    items: list[LessonModuleItemOut | QuizModuleItemOut | PracticeModuleItemOut] = []
    published_lesson_ids = {
        item.lesson.id
        for item in module.items
        if item.lesson is not None and item.lesson.status is ContentStatus.PUBLISHED
    }
    for item in sorted(module.items, key=lambda current: current.position):
        if item.lesson is not None:
            if published_only and item.lesson.status is not ContentStatus.PUBLISHED:
                continue
            items.append(
                LessonModuleItemOut(
                    id=item.id,
                    position=item.position,
                    lesson=lesson_out(item.lesson),
                )
            )
        elif item.quiz is not None:
            if published_only and (
                item.quiz.status is not ContentStatus.PUBLISHED
                or (
                    item.quiz.lesson_id is not None
                    and item.quiz.lesson_id not in published_lesson_ids
                )
            ):
                continue
            items.append(
                QuizModuleItemOut(
                    id=item.id,
                    position=item.position,
                    quiz=quiz_out(item.quiz, asset_base_url=asset_base_url),
                )
            )
        elif item.practice_set is not None:
            if published_only and item.practice_set.status is not ContentStatus.PUBLISHED:
                continue
            items.append(
                PracticeModuleItemOut(
                    id=item.id,
                    position=item.position,
                    practice_set=PracticeSetModuleSummary.model_validate(item.practice_set),
                )
            )
    return ModuleTreeOut(
        id=module.id,
        course_id=module.course_id,
        title=module.title,
        slug=module.slug,
        summary=module.summary,
        position=module.position,
        status=module.status,
        items=items,
    )


def course_tree_out(
    course: Course,
    *,
    published_only: bool,
    asset_base_url: str,
) -> CourseTreeOut:
    modules = sorted(course.modules, key=lambda item: item.position)
    if published_only:
        modules = [item for item in modules if item.status is ContentStatus.PUBLISHED]
    base = course_out(course, asset_base_url=asset_base_url)
    return CourseTreeOut(
        **base.model_dump(),
        modules=[
            module_tree_out(
                module,
                published_only=published_only,
                asset_base_url=asset_base_url,
            )
            for module in modules
        ],
    )
