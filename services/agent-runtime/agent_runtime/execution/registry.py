from __future__ import annotations

from .contracts import ExecutionBackend


class ExecutionBackendRegistry:
    def __init__(self, backends: list[ExecutionBackend] | None = None) -> None:
        self._backends: dict[str, ExecutionBackend] = {}
        for backend in backends or []:
            self.register(backend)

    def register(self, backend: ExecutionBackend) -> None:
        self._backends[backend.kind] = backend

    def resolve(self, backend_kind: str) -> ExecutionBackend:
        try:
            return self._backends[backend_kind]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"No execution backend registered for {backend_kind!r}") from exc
