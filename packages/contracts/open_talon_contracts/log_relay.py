from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .log_management import RotatingFileWriter, RotationPolicy


_CHUNK_SIZE = 64 * 1024
_DEFAULT_MAX_BYTES = 20 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 10


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a subprocess and rotate its combined logs.")
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.getenv("OPEN_TALON_SERVICE_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES)),
    )
    parser.add_argument(
        "--backup-count",
        type=int,
        default=int(os.getenv("OPEN_TALON_SERVICE_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT)),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        parser.error("expected a command after --")
    args.command = args.command[1:]
    return args


def _forward_signal(child: subprocess.Popen[bytes], signum: int) -> None:
    if child.poll() is None:
        child.send_signal(signum)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    policy = RotationPolicy(max_bytes=args.max_bytes, backup_count=args.backup_count)

    child = subprocess.Popen(
        args.command,
        cwd=args.cwd,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, lambda received, _frame, child=child: _forward_signal(child, received))

    assert child.stdout is not None
    with RotatingFileWriter(Path(args.log_file), policy) as writer:
        while True:
            chunk = child.stdout.read1(_CHUNK_SIZE)
            if not chunk:
                break
            writer.write(chunk)

    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
