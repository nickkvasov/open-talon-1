from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_system_lifecycle_scripts_parse_and_are_executable() -> None:
    for script_name in ("system-init.sh", "system-repair.sh", "system-reset.sh"):
        script_path = ROOT_DIR / "scripts" / script_name
        assert script_path.exists()
        assert script_path.stat().st_mode & stat.S_IXUSR
        subprocess.run(["bash", "-n", str(script_path)], check=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(ROOT_DIR / "scripts" / "system_repair.py"),
        ],
        check=True,
    )


def test_open_talon_exposes_system_lifecycle_commands() -> None:
    launcher = (ROOT_DIR / "open-talon").read_text(encoding="utf-8")

    assert "./open-talon init" in launcher
    assert "./open-talon repair" in launcher
    assert "./open-talon reset" in launcher
    assert "scripts/system-init.sh" in launcher
    assert "scripts/system-repair.sh" in launcher
    assert "scripts/system-reset.sh" in launcher
