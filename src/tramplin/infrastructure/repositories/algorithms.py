from collections.abc import Sequence
from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.algorithms import (
    AlgorithmJobOutbox,
    AlgorithmProblem,
    AlgorithmProgress,
    AlgorithmSubmission,
    AlgorithmTemplate,
    AlgorithmTestCase,
    PracticeSession,
    PracticeSet,
    PracticeSetProblem,
    algorithm_problem_tags,
)
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmVerdict,
    ContentStatus,
    SubmissionKind,
    SubmissionStatus,
)
from tramplin.models.tags import Tag
from tramplin.models.users import User

_DIFFICULTY_ORDER = case(
    (AlgorithmProblem.difficulty == AlgorithmDifficulty.EASY, 0),
    (AlgorithmProblem.difficulty == AlgorithmDifficulty.MEDIUM, 1),
    else_=2,
)


class AlgorithmRepository(Repository):
    async def list_problems(self, *, limit: int, offset: int) -> tuple[list[AlgorithmProblem], int]:
        stmt = (
            select(AlgorithmProblem)
            .order_by(AlgorithmProblem.created_at.desc())
            .options(
                selectinload(AlgorithmProblem.test_cases),
                selectinload(AlgorithmProblem.templates),
                selectinload(AlgorithmProblem.tags),
            )
        )
        total = await self._session.scalar(select(func.count()).select_from(AlgorithmProblem))
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    async def get_problem(
        self, problem_id: uuid.UUID, *, published_only: bool
    ) -> AlgorithmProblem | None:
        stmt = (
            select(AlgorithmProblem)
            .where(AlgorithmProblem.id == problem_id)
            .options(
                selectinload(AlgorithmProblem.test_cases),
                selectinload(AlgorithmProblem.templates),
                selectinload(AlgorithmProblem.tags),
            )
        )
        if published_only:
            stmt = stmt.where(AlgorithmProblem.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_published_problems(
        self,
        *,
        difficulty: AlgorithmDifficulty | None,
        tag_id: uuid.UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlgorithmProblem], int]:
        filters = [AlgorithmProblem.status == ContentStatus.PUBLISHED]
        if difficulty is not None:
            filters.append(AlgorithmProblem.difficulty == difficulty)
        if tag_id is not None:
            filters.append(AlgorithmProblem.tags.any(Tag.id == tag_id))
        if query:
            filters.append(AlgorithmProblem.title.ilike(f"%{query}%"))

        total = await self._session.scalar(
            select(func.count()).select_from(AlgorithmProblem).where(*filters)
        )
        stmt = (
            select(AlgorithmProblem)
            .where(*filters)
            .options(selectinload(AlgorithmProblem.templates), selectinload(AlgorithmProblem.tags))
            .order_by(_DIFFICULTY_ORDER, AlgorithmProblem.title)
            .limit(limit)
            .offset(offset)
        )
        return list(await self._session.scalars(stmt)), int(total or 0)

    async def published_tags(self) -> list[Tag]:
        stmt = (
            select(Tag)
            .join(algorithm_problem_tags, Tag.id == algorithm_problem_tags.c.tag_id)
            .join(AlgorithmProblem, AlgorithmProblem.id == algorithm_problem_tags.c.problem_id)
            .where(AlgorithmProblem.status == ContentStatus.PUBLISHED)
            .distinct()
            .order_by(Tag.name)
        )
        return list(await self._session.scalars(stmt))

    async def progress_map(
        self, user_id: uuid.UUID, problem_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, AlgorithmProgress]:
        if not problem_ids:
            return {}
        stmt = select(AlgorithmProgress).where(
            AlgorithmProgress.user_id == user_id,
            AlgorithmProgress.problem_id.in_(problem_ids),
        )
        return {item.problem_id: item for item in await self._session.scalars(stmt)}

    def add_problem(self, problem: AlgorithmProblem) -> AlgorithmProblem:
        self._session.add(problem)
        return problem

    async def delete_problem(self, problem: AlgorithmProblem) -> None:
        # Тест-кейсы и шаблоны каскадно удаляются на уровне БД (FK ondelete="CASCADE").
        await self.delete(problem)

    async def get_test_case(self, case_id: uuid.UUID) -> AlgorithmTestCase | None:
        return await self._session.get(AlgorithmTestCase, case_id)

    def add_test_case(self, case: AlgorithmTestCase) -> AlgorithmTestCase:
        self._session.add(case)
        return case

    async def delete_test_case(self, case: AlgorithmTestCase) -> None:
        await self.delete(case)

    async def get_template(self, problem_id: uuid.UUID, language: str) -> AlgorithmTemplate | None:
        return await self._session.get(AlgorithmTemplate, (problem_id, language))

    def add_template(self, template: AlgorithmTemplate) -> AlgorithmTemplate:
        self._session.add(template)
        return template

    async def delete_template(self, template: AlgorithmTemplate) -> None:
        await self._session.delete(template)

    async def get_set(self, set_id: uuid.UUID, *, published_only: bool) -> PracticeSet | None:
        stmt = (
            select(PracticeSet)
            .where(PracticeSet.id == set_id)
            .options(
                selectinload(PracticeSet.problems)
                .selectinload(PracticeSetProblem.problem)
                .selectinload(AlgorithmProblem.test_cases),
                selectinload(PracticeSet.problems)
                .selectinload(PracticeSetProblem.problem)
                .selectinload(AlgorithmProblem.templates),
            )
        )
        if published_only:
            stmt = stmt.where(PracticeSet.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_sets(self, *, limit: int, offset: int) -> tuple[list[PracticeSet], int]:
        stmt = (
            select(PracticeSet)
            .order_by(PracticeSet.created_at.desc())
            .options(selectinload(PracticeSet.problems).selectinload(PracticeSetProblem.problem))
        )
        total = await self._session.scalar(select(func.count()).select_from(PracticeSet))
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    def add_set(self, practice_set: PracticeSet) -> PracticeSet:
        self._session.add(practice_set)
        return practice_set

    async def delete_set(self, practice_set: PracticeSet) -> None:
        # Задачи набора каскадно удаляются на уровне БД (FK ondelete="CASCADE").
        await self.delete(practice_set)

    def add_set_problem(self, item: PracticeSetProblem) -> PracticeSetProblem:
        self._session.add(item)
        return item

    async def delete_set_problem(self, item: PracticeSetProblem) -> None:
        await self._session.delete(item)

    async def get_set_problem(
        self, set_id: uuid.UUID, problem_id: uuid.UUID
    ) -> PracticeSetProblem | None:
        return await self._session.get(PracticeSetProblem, (set_id, problem_id))

    def add_session(self, practice_session: PracticeSession) -> PracticeSession:
        self._session.add(practice_session)
        return practice_session

    async def get_session(
        self, session_id: uuid.UUID, *, for_update: bool = False
    ) -> PracticeSession | None:
        stmt = (
            select(PracticeSession)
            .where(PracticeSession.id == session_id)
            .options(selectinload(PracticeSession.practice_set).selectinload(PracticeSet.problems))
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def lock_user(self, user_id: uuid.UUID) -> None:
        await self._session.scalar(select(User.id).where(User.id == user_id).with_for_update())

    def add_submission(self, submission: AlgorithmSubmission) -> AlgorithmSubmission:
        self._session.add(submission)
        return submission

    def add_outbox(self, event: AlgorithmJobOutbox) -> AlgorithmJobOutbox:
        self._session.add(event)
        return event

    async def claim_outbox(self) -> AlgorithmJobOutbox | None:
        stmt = (
            select(AlgorithmJobOutbox)
            .where(AlgorithmJobOutbox.dispatched_at.is_(None))
            .order_by(AlgorithmJobOutbox.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_submission(
        self, submission_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmSubmission | None:
        stmt = select(AlgorithmSubmission).where(AlgorithmSubmission.id == submission_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_accepted_submissions(
        self, user_id: uuid.UUID, problem_id: uuid.UUID, *, limit: int
    ) -> list[AlgorithmSubmission]:
        stmt = (
            select(AlgorithmSubmission)
            .where(
                AlgorithmSubmission.user_id == user_id,
                AlgorithmSubmission.problem_id == problem_id,
                AlgorithmSubmission.kind == SubmissionKind.SUBMIT,
                AlgorithmSubmission.verdict == AlgorithmVerdict.ACCEPTED,
            )
            .order_by(AlgorithmSubmission.finished_at.desc())
            .limit(limit)
        )
        return list((await self._session.scalars(stmt)).all())

    async def active_submissions(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(AlgorithmSubmission)
            .where(
                AlgorithmSubmission.user_id == user_id,
                AlgorithmSubmission.status.in_([SubmissionStatus.QUEUED, SubmissionStatus.RUNNING]),
            )
        )
        return int(await self._session.scalar(stmt) or 0)

    async def submission_count(
        self,
        *,
        user_id: uuid.UUID,
        since: datetime | None = None,
        session_id: uuid.UUID | None = None,
        problem_id: uuid.UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(AlgorithmSubmission)
            .where(AlgorithmSubmission.user_id == user_id)
        )
        if since is not None:
            stmt = stmt.where(AlgorithmSubmission.created_at >= since)
        if session_id is not None:
            stmt = stmt.where(AlgorithmSubmission.session_id == session_id)
        if problem_id is not None:
            stmt = stmt.where(AlgorithmSubmission.problem_id == problem_id)
        return int(await self._session.scalar(stmt) or 0)

    async def claim_submission(self, *, stale_before: datetime) -> AlgorithmSubmission | None:
        stmt = (
            select(AlgorithmSubmission)
            .where(
                or_(
                    AlgorithmSubmission.status == SubmissionStatus.QUEUED,
                    (
                        (AlgorithmSubmission.status == SubmissionStatus.RUNNING)
                        & (AlgorithmSubmission.claimed_at < stale_before)
                    ),
                )
            )
            .order_by(AlgorithmSubmission.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_progress(
        self, user_id: uuid.UUID, problem_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmProgress | None:
        stmt = select(AlgorithmProgress).where(
            AlgorithmProgress.user_id == user_id,
            AlgorithmProgress.problem_id == problem_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    def add_progress(self, progress: AlgorithmProgress) -> AlgorithmProgress:
        self._session.add(progress)
        return progress

    async def queue_stats(self) -> tuple[int, int, int]:
        queued = await self._session.scalar(
            select(func.count())
            .select_from(AlgorithmSubmission)
            .where(AlgorithmSubmission.status == SubmissionStatus.QUEUED)
        )
        running = await self._session.scalar(
            select(func.count())
            .select_from(AlgorithmSubmission)
            .where(AlgorithmSubmission.status == SubmissionStatus.RUNNING)
        )
        pending_outbox = await self._session.scalar(
            select(func.count())
            .select_from(AlgorithmJobOutbox)
            .where(AlgorithmJobOutbox.dispatched_at.is_(None))
        )
        return int(queued or 0), int(running or 0), int(pending_outbox or 0)
