from dataclasses import dataclass, field

import uuid_utils.compat as uuid

from tramplin.core.errors import UnprocessableError
from tramplin.models.content import Course, Module, ModuleItem, Track
from tramplin.models.enums import ContentStatus
from tramplin.services.algorithms import AlgorithmAuthoringService
from tramplin.services.courses import CourseService
from tramplin.services.lessons import LessonService
from tramplin.services.modules import ModuleService
from tramplin.services.quizzes import QuizService
from tramplin.services.tracks import TrackService


@dataclass
class PublishSkip:
    id: uuid.UUID
    kind: str
    title: str
    reason: str


@dataclass
class PublishReport:
    published: list[uuid.UUID] = field(default_factory=list)
    skipped: list[PublishSkip] = field(default_factory=list)


def _item_kind_title_status(item: ModuleItem) -> tuple[str, str, ContentStatus, uuid.UUID]:
    if item.lesson is not None:
        return "lesson", item.lesson.title, item.lesson.status, item.lesson.id
    if item.quiz is not None:
        return "quiz", item.quiz.title, item.quiz.status, item.quiz.id
    if item.practice_set is not None:
        return (
            "practice_set",
            item.practice_set.title,
            item.practice_set.status,
            item.practice_set.id,
        )
    # num_nonnulls(lesson_id, quiz_id, practice_set_id) = 1 на уровне БД гарантирует,
    # что сюда мы не попадём; RuntimeError — не UnprocessableError, чтобы не потеряться
    # среди пропущенных по валидации пунктов, если гарантия всё-таки нарушится.
    raise RuntimeError("У материала модуля не задан ни урок, ни тест, ни набор практики")


class PublishCascadeService:
    """
    «Опубликовать всё содержимое» одним запросом вместо N параллельных PATCH
    с фронта на каждый урок/тест/набор дерева — раньше это заканчивалось и
    лишней нагрузкой на API, и рассинхроном экрана с БД при частичном сбое
    (Promise.all падал целиком, а часть объектов уже успевала опубликоваться).

    Best-effort: публикует всё, что проходит валидацию, пропускает
    остальное — никогда не трогает то, что уже опубликовано, и не снимает
    публикацию при пропуске. Единственный смысл этого сервиса —
    переиспользовать validation, которая уже живёт в LessonService/
    QuizService/AlgorithmAuthoringService.update_set, а не пересчитывать её
    заново: причина пропуска здесь всегда та же строка, что увидит автор
    при точечном редактировании конкретного урока/теста/набора. Поэтому
    сервис — редкое исключение из правила «сервисы зависят от репозиториев,
    а не друг от друга»: депендить напрямую от репозиториев означало бы
    задваивать эти проверки.
    """

    def __init__(
        self,
        modules: ModuleService,
        courses: CourseService,
        tracks: TrackService,
        lessons: LessonService,
        quizzes: QuizService,
        algorithm_authoring: AlgorithmAuthoringService,
    ) -> None:
        self._modules = modules
        self._courses = courses
        self._tracks = tracks
        self._lessons = lessons
        self._quizzes = quizzes
        self._algorithm_authoring = algorithm_authoring

    async def _publish_item(
        self, item: ModuleItem, actor_id: uuid.UUID, report: PublishReport
    ) -> None:
        kind, title, status, item_id = _item_kind_title_status(item)
        if status is ContentStatus.PUBLISHED:
            return
        changes = {"status": ContentStatus.PUBLISHED}
        try:
            if kind == "lesson":
                await self._lessons.update(item_id, changes, actor_id)
            elif kind == "quiz":
                await self._quizzes.update(item_id, changes, actor_id)
            else:
                await self._algorithm_authoring.update_set(item_id, changes, actor_id)
        except UnprocessableError as cause:
            report.skipped.append(PublishSkip(item_id, kind, title, cause.message))
            return
        report.published.append(item_id)

    async def _publish_module(
        self, module: Module, actor_id: uuid.UUID, report: PublishReport
    ) -> None:
        if module.status is not ContentStatus.PUBLISHED:
            await self._modules.update(module.id, {"status": ContentStatus.PUBLISHED}, actor_id)
            report.published.append(module.id)
        for item in module.items:
            await self._publish_item(item, actor_id, report)

    async def _publish_course(
        self, course: Course, actor_id: uuid.UUID, report: PublishReport
    ) -> None:
        if course.status is not ContentStatus.PUBLISHED:
            await self._courses.update(course.id, {"status": ContentStatus.PUBLISHED}, actor_id)
            report.published.append(course.id)
        for module in course.modules:
            await self._publish_module(module, actor_id, report)

    async def publish_module(self, module_id: uuid.UUID, actor_id: uuid.UUID) -> PublishReport:
        module = await self._modules.get_tree(module_id)
        report = PublishReport()
        await self._publish_module(module, actor_id, report)
        return report

    async def publish_course(self, course_id: uuid.UUID, actor_id: uuid.UUID) -> PublishReport:
        course = await self._courses.get_tree(course_id)
        report = PublishReport()
        await self._publish_course(course, actor_id, report)
        return report

    async def publish_track(self, track_id: uuid.UUID, actor_id: uuid.UUID) -> PublishReport:
        track: Track = await self._tracks.get_tree(track_id)
        report = PublishReport()
        if track.status is not ContentStatus.PUBLISHED:
            await self._tracks.update(track.id, {"status": ContentStatus.PUBLISHED}, actor_id)
            report.published.append(track.id)
        for link in track.courses:
            course = await self._courses.get_tree(link.course_id)
            await self._publish_course(course, actor_id, report)
        return report
