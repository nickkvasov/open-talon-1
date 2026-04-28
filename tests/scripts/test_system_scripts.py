from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_system_lifecycle_scripts_parse_and_are_executable() -> None:
    for script_name in ("dbmate.sh", "system-init.sh", "system-repair.sh", "system-reset.sh"):
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
            str(ROOT_DIR / "scripts" / "migrations.py"),
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


def test_migration_helper_creates_timestamped_dbmate_style_files(tmp_path) -> None:
    env = os.environ.copy()
    env["DBMATE_MIGRATIONS_DIR"] = str(tmp_path)
    env["OPEN_TALON_MIGRATION_TIMESTAMP"] = "20260102030405"
    env["PYTHONPATH"] = (
        f"{ROOT_DIR / 'packages' / 'contracts'}:"
        f"{ROOT_DIR / 'services' / 'core-collab'}:"
        f"{env.get('PYTHONPATH', '')}"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT_DIR / "scripts" / "migrations.py"),
            "new",
            "add_test_table",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    migration_path = tmp_path / "20260102030405_add_test_table.sql"
    assert result.stdout.strip() == str(migration_path)
    assert migration_path.read_text(encoding="utf-8") == (
        "-- migrate:up\n\n-- migrate:down\n"
    )


def test_dbmate_wrapper_delegates_to_python_migration_helper() -> None:
    wrapper = (ROOT_DIR / "scripts" / "dbmate.sh").read_text(encoding="utf-8")

    assert "scripts/migrations.py" in wrapper
    assert "exec dbmate" not in wrapper
