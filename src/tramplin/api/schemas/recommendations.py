import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.tags import TagOut
from tramplin.models.enums import AlgorithmDifficulty


class RecommendedCourseOut(ApiModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    est_hours: int | None
    tags: list[TagOut]


class RecommendedAlgorithmOut(ApiModel):
    id: uuid.UUID
    title: str
    difficulty: AlgorithmDifficulty
    tags: list[TagOut]


class RecommendationsOut(ApiModel):
    courses: list[RecommendedCourseOut]
    algorithms: list[RecommendedAlgorithmOut]
