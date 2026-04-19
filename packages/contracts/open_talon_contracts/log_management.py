from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterator, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - only used on non-POSIX platforms
    fcntl = None


_DEFAULT_ENCODING = "utf-8"


def _get_int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True)
class RotationPolicy:
    max_bytes: int
    backup_count: int

    @property
    def enabled(self) -> bool:
        return self.max_bytes > 0 and self.backup_count > 0

    @classmethod
    def from_env(
        cls,
        *,
        max_bytes_var: str,
        backup_count_var: str,
        default_max_bytes: int,
        default_backup_count: int,
    ) -> "RotationPolicy":
        return cls(
            max_bytes=_get_int_from_env(max_bytes_var, default_max_bytes),
            backup_count=_get_int_from_env(backup_count_var, default_backup_count),
        )


def _rotate_files(path: Path, backup_count: int) -> None:
    if backup_count <= 0 or not path.exists():
        return

    oldest_path = path.with_name(f"{path.name}.{backup_count}")
    if oldest_path.exists():
        oldest_path.unlink()

    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            source.replace(target)

    path.replace(path.with_name(f"{path.name}.1"))


class RotatingFileWriter:
    def __init__(self, path: str | Path, policy: RotationPolicy) -> None:
        self.path = Path(path)
        self.policy = policy
        self._handle = None
        self._current_size = 0

    def __enter__(self) -> "RotatingFileWriter":
        self._open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("ab")
        self._current_size = self.path.stat().st_size if self.path.exists() else 0

    def close(self) -> None:
        if self._handle is None:
            return
        self._handle.close()
        self._handle = None

    def write(self, payload: bytes) -> None:
        if self._handle is None:
            self._open()

        if self.policy.enabled and self._current_size > 0:
            projected_size = self._current_size + len(payload)
            if projected_size > self.policy.max_bytes:
                self.close()
                _rotate_files(self.path, self.policy.backup_count)
                self._open()

        assert self._handle is not None
        self._handle.write(payload)
        self._handle.flush()
        self._current_size += len(payload)


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_bytes_with_rotation(
    path: str | Path,
    payloads: Sequence[bytes],
    *,
    policy: RotationPolicy,
) -> None:
    if not payloads:
        return

    target_path = Path(path)
    lock_path = target_path.with_name(f"{target_path.name}.lock")
    with _exclusive_lock(lock_path):
        with RotatingFileWriter(target_path, policy) as writer:
            for payload in payloads:
                writer.write(payload)


def append_jsonl_with_rotation(
    path: str | Path,
    payloads: Sequence[str],
    *,
    policy: RotationPolicy,
    encoding: str = _DEFAULT_ENCODING,
) -> None:
    encoded_payloads = [
        payload.encode(encoding) + b"\n"
        for payload in payloads
    ]
    append_bytes_with_rotation(path, encoded_payloads, policy=policy)
