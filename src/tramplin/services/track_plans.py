from __future__ import annotations

import uuid_utils.compat as uuid

from tramplin.models.content import Course, Track, TrackCourse
from tramplin.models.enums import ContentStatus
from tramplin.services.contracts import Transaction
from tramplin.services.course_plan_schemas import TrackPlanApply
from tramplin.services.courses import CourseRepositoryPort
from tramplin.services.plan_report import PlanChange, PlanReport
from tramplin.services.tracks import TrackRepositoryPort

ADDITIVE_WARNING = "Additive-only: курсы трека вне плана сохраняются и уходят в конец."


class TrackPlanService:
    """Декларативно собирает трек из существующих курсов по их slug.

    Трек matching по slug; курсы вне плана не открепляются, а уходят в конец. Статус
    существующего трека не меняется: план не снимает публикацию. preview — тот же код
    без commit.
    """

    def __init__(
        self,
        transaction: Transaction,
        tracks: TrackRepositoryPort,
        courses: CourseRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._tracks = tracks
        self._courses = courses

    async def validate(self, plan: TrackPlanApply) -> PlanReport:
        report = PlanReport()
        if not plan.course_slugs:
            report.warning(plan.slug, "empty_track", "Трек без курсов")
        for slug in plan.course_slugs:
            if await self._courses.get_by_slug(slug, published_only=False) is None:
                report.error(
                    f"{plan.slug}/{slug}",
                    "unknown_course",
                    f"Курса '{slug}' нет: сначала создайте его планом курса",
                )
        return report

    async def preview(self, plan: TrackPlanApply, actor_id: uuid.UUID) -> PlanReport:
        report = await self.validate(plan)
        if report.valid:
            await self._apply(plan, actor_id, report)
            await self._transaction.flush()
        return report

    async def apply(self, plan: TrackPlanApply, actor_id: uuid.UUID) -> tuple[Track, PlanReport]:
        report = await self.validate(plan)
        report.raise_if_invalid()
        track = await self._apply(plan, actor_id, report)
        await self._transaction.commit()
        return track, report

    async def _apply(self, plan: TrackPlanApply, actor_id: uuid.UUID, report: PlanReport) -> Track:
        track = await self._tracks.get_by_slug(plan.slug, published_only=False)
        links: list[TrackCourse] = []
        if track is None:
            track = Track(
                title=plan.title,
                slug=plan.slug,
                description=plan.description,
                color=plan.color,
                status=ContentStatus.DRAFT,
            )
            track.courses = []
            change = report.create("track", plan.slug, track, actor_id)
            self._tracks.add(track)
            await self._transaction.flush()
        else:
            report.warnings.append(ADDITIVE_WARNING)
            change = report.update(
                "track",
                plan.slug,
                track,
                {"title": plan.title, "description": plan.description, "color": plan.color},
                actor_id,
            )
            links = sorted(
                await self._tracks.list_course_links(track.id), key=lambda link: link.position
            )

        courses: list[Course] = []
        for slug in plan.course_slugs:
            course = await self._courses.get_by_slug(slug, published_only=False)
            if course is not None:
                courses.append(course)
        await self._sync_links(track, plan.slug, courses, links, change, actor_id, report)
        return track

    async def _sync_links(
        self,
        track: Track,
        path: str,
        courses: list[Course],
        links: list[TrackCourse],
        change: PlanChange,
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> None:
        order_before = [link.course_id for link in links]
        by_course = {link.course_id: link for link in links}
        desired_ids = {course.id for course in courses}
        # Как и с модулями курса: уводим существующие связи во временный отрицательный
        # диапазон, чтобы финальная расстановка не упёрлась в uq на (track_id, position).
        for offset, link in enumerate(links):
            link.position = -(offset + 1)
        if links:
            await self._transaction.flush()

        ordered: list[TrackCourse] = []
        for course in courses:
            existing = by_course.get(course.id)
            if existing is not None:
                ordered.append(existing)
                continue
            link = TrackCourse(
                track_id=track.id,
                course_id=course.id,
                position=len(ordered),
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._tracks.add_course_link(link)
            report.changes.append(
                PlanChange("create", "track_course", f"{path}/{course.slug}", course)
            )
            ordered.append(link)
        ordered.extend(link for link in links if link.course_id not in desired_ids)
        for position, link in enumerate(ordered):
            link.position = position
            link.updated_by = actor_id
        existing_ids = set(order_before)
        if [link.course_id for link in ordered if link.course_id in existing_ids] != order_before:
            change.touch("course_order")
