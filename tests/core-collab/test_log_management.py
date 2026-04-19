from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time


_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
if _CONTRACTS_DIR not in sys.path:
    sys.path.insert(0, _CONTRACTS_DIR)

from open_talon_contracts.log_management import RotationPolicy, append_bytes_with_rotation  # noqa: E402


def test_append_bytes_with_rotation_keeps_recent_segments(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"
    policy = RotationPolicy(max_bytes=17, backup_count=2)

    append_bytes_with_rotation(
        log_path,
        [b"line-01\n", b"line-02\n", b"line-03\n", b"line-04\n"],
        policy=policy,
    )

    assert log_path.read_text(encoding="utf-8") == "line-03\nline-04\n"
    assert (tmp_path / "service.log.1").read_text(encoding="utf-8") == "line-01\nline-02\n"


def test_log_relay_rotates_subprocess_output(tmp_path: Path) -> None:
    log_path = tmp_path / "relay.log"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{_CONTRACTS_DIR}:{existing_pythonpath}"
        if existing_pythonpath
        else _CONTRACTS_DIR
    )

    command = [
        sys.executable,
        "-m",
        "open_talon_contracts.log_relay",
        "--log-file",
        str(log_path),
        "--cwd",
        str(tmp_path),
        "--max-bytes",
        "50000",
        "--backup-count",
        "2",
        "--",
        sys.executable,
        "-c",
        "for index in range(15000): print(f'entry-{index:05d}')",
    ]
    result = subprocess.run(command, check=False, env=env, cwd=tmp_path)

    assert result.returncode == 0
    assert log_path.exists()
    assert (tmp_path / "relay.log.1").exists()
    assert "entry-14999" in log_path.read_text(encoding="utf-8")


def test_log_relay_streams_output_before_child_exit(tmp_path: Path) -> None:
    log_path = tmp_path / "stream.log"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{_CONTRACTS_DIR}:{existing_pythonpath}"
        if existing_pythonpath
        else _CONTRACTS_DIR
    )

    command = [
        sys.executable,
        "-m",
        "open_talon_contracts.log_relay",
        "--log-file",
        str(log_path),
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        (
            "import sys, time; "
            "print('first-line', flush=True); "
            "time.sleep(1.5); "
            "print('second-line', flush=True)"
        ),
    ]
    proc = subprocess.Popen(command, env=env, cwd=tmp_path)
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if log_path.exists() and "first-line" in log_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("relay did not stream child output while the child was still running")
    finally:
        proc.wait(timeout=5)

    content = log_path.read_text(encoding="utf-8")
    assert "first-line" in content
    assert "second-line" in content
