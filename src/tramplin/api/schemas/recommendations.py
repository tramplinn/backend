import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import AlgorithmDifficulty


class RecommendedCourseOut(ApiModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    est_hours: int | None
    topics: list[str]


class RecommendedAlgorithmOut(ApiModel):
    id: uuid.UUID
    title: str
    difficulty: AlgorithmDifficulty
    topics: list[str]


class RecommendationsOut(ApiModel):
    courses: list[RecommendedCourseOut]
    algorithms: list[RecommendedAlgorithmOut]
