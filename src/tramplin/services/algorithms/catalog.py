from dataclasses import dataclass

from tramplin.models.algorithms import AlgorithmProblem, AlgorithmProgress
from tramplin.models.tags import Tag


@dataclass(frozen=True, slots=True)
class ProblemCatalog:
    """Каталог тренажёра: задачи вместе с прогрессом текущего пользователя."""

    items: list[tuple[AlgorithmProblem, AlgorithmProgress | None]]
    tags: list[Tag]
    total: int
