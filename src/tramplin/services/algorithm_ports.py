from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

import uuid_utils.compat as uuid

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
)
from tramplin.models.content import Module, ModuleItem
from tramplin.models.enums import AlgorithmDifficulty
from tramplin.models.tags import Tag


class AlgorithmAuthoringRepositoryPort(Protocol):
    async def list_problems(
        self, *, limit: int, offset: int
    ) -> tuple[list[AlgorithmProblem], int]: ...

    async def get_problem(
        self, problem_id: uuid.UUID, *, published_only: bool
    ) -> AlgorithmProblem | None: ...

    def add_problem(self, problem: AlgorithmProblem) -> AlgorithmProblem: ...

    async def delete_problem(self, problem: AlgorithmProblem) -> None: ...

    async def get_test_case(self, case_id: uuid.UUID) -> AlgorithmTestCase | None: ...

    def add_test_case(self, case: AlgorithmTestCase) -> AlgorithmTestCase: ...

    async def delete_test_case(self, case: AlgorithmTestCase) -> None: ...

    async def get_template(
        self, problem_id: uuid.UUID, language: str
    ) -> AlgorithmTemplate | None: ...

    def add_template(self, template: AlgorithmTemplate) -> AlgorithmTemplate: ...

    async def delete_template(self, template: AlgorithmTemplate) -> None: ...

    async def get_set(self, set_id: uuid.UUID, *, published_only: bool) -> PracticeSet | None: ...

    async def list_sets(self, *, limit: int, offset: int) -> tuple[list[PracticeSet], int]: ...

    def add_set(self, practice_set: PracticeSet) -> PracticeSet: ...

    async def delete_set(self, practice_set: PracticeSet) -> None: ...

    def add_set_problem(self, item: PracticeSetProblem) -> PracticeSetProblem: ...

    async def delete_set_problem(self, item: PracticeSetProblem) -> None: ...

    async def get_set_problem(
        self, set_id: uuid.UUID, problem_id: uuid.UUID
    ) -> PracticeSetProblem | None: ...


class AlgorithmModuleRepositoryPort(Protocol):
    async def get_for_update(self, module_id: uuid.UUID) -> Module | None: ...

    async def list_items(self, module_id: uuid.UUID) -> list[ModuleItem]: ...

    def add_item(self, item: ModuleItem) -> ModuleItem: ...


class AlgorithmPracticeRepositoryPort(Protocol):
    async def get_problem(
        self, problem_id: uuid.UUID, *, published_only: bool
    ) -> AlgorithmProblem | None: ...

    async def list_published_problems(
        self,
        *,
        difficulty: AlgorithmDifficulty | None,
        tag_id: uuid.UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlgorithmProblem], int]: ...

    async def published_tags(self) -> list[Tag]: ...

    async def progress_map(
        self, user_id: uuid.UUID, problem_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, AlgorithmProgress]: ...

    async def get_set(self, set_id: uuid.UUID, *, published_only: bool) -> PracticeSet | None: ...

    def add_session(self, practice_session: PracticeSession) -> PracticeSession: ...

    async def get_session(
        self, session_id: uuid.UUID, *, for_update: bool = False
    ) -> PracticeSession | None: ...

    async def lock_user(self, user_id: uuid.UUID) -> None: ...

    def add_submission(self, submission: AlgorithmSubmission) -> AlgorithmSubmission: ...

    def add_outbox(self, event: AlgorithmJobOutbox) -> AlgorithmJobOutbox: ...

    async def get_submission(
        self, submission_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmSubmission | None: ...

    async def active_submissions(self, user_id: uuid.UUID) -> int: ...

    async def list_accepted_submissions(
        self, user_id: uuid.UUID, problem_id: uuid.UUID, *, limit: int
    ) -> list[AlgorithmSubmission]: ...

    async def submission_count(
        self,
        *,
        user_id: uuid.UUID,
        since: datetime | None = None,
        session_id: uuid.UUID | None = None,
        problem_id: uuid.UUID | None = None,
    ) -> int: ...

    async def get_progress(
        self, user_id: uuid.UUID, problem_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmProgress | None: ...

    def add_progress(self, progress: AlgorithmProgress) -> AlgorithmProgress: ...


class AlgorithmWorkerRepositoryPort(Protocol):
    async def claim_submission(self, *, stale_before: datetime) -> AlgorithmSubmission | None: ...

    async def get_submission(
        self, submission_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmSubmission | None: ...

    async def get_problem(
        self, problem_id: uuid.UUID, *, published_only: bool
    ) -> AlgorithmProblem | None: ...

    async def get_progress(
        self, user_id: uuid.UUID, problem_id: uuid.UUID, *, for_update: bool = False
    ) -> AlgorithmProgress | None: ...

    def add_progress(self, progress: AlgorithmProgress) -> AlgorithmProgress: ...


class AlgorithmDispatchRepositoryPort(Protocol):
    async def claim_outbox(self) -> AlgorithmJobOutbox | None: ...


class AlgorithmOperationsRepositoryPort(Protocol):
    async def queue_stats(self) -> tuple[int, int, int]: ...
