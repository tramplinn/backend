from tramplin.core.errors import RunnerUnavailableError
from tramplin.services.algorithm_ports import AlgorithmOperationsRepositoryPort
from tramplin.services.contracts import CodeRunner, RunnerLanguage


class AlgorithmOperationsService:
    def __init__(self, algorithms: AlgorithmOperationsRepositoryPort, runner: CodeRunner) -> None:
        self._algorithms = algorithms
        self._runner = runner

    async def health(self) -> tuple[str, int]:
        try:
            languages = await self._runner.languages()
        except RunnerUnavailableError:
            return "unavailable", 0
        expected = 8
        return ("healthy" if len(languages) == expected else "degraded"), len(languages)

    async def languages(self) -> list[RunnerLanguage]:
        return await self._runner.languages()

    async def queue(self) -> tuple[int, int, int]:
        return await self._algorithms.queue_stats()
