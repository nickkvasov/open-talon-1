from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_runner():
    module_path = ROOT_DIR / "scripts" / "run_live_tests.py"
    spec = importlib.util.spec_from_file_location("run_live_tests", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_test_runner_exposes_all_expected_suites_and_groups() -> None:
    runner = _load_runner()

    assert set(runner.SUITES) == {
        "config",
        "compose",
        "mcp",
        "compaction",
        "tinker",
        "operational",
        "anchor",
        "retriever",
        "system-plugins",
        "web-search-internet",
        "xwiki",
    }
    assert runner.GROUPS["all"] == runner.SUITE_ORDER
    assert runner.GROUPS["default-stack"] == ("operational", "anchor", "retriever")
    assert runner.GROUPS["providers"] == (
        "system-plugins",
        "web-search-internet",
        "retriever",
        "xwiki",
    )


def test_live_test_runner_expands_fractional_groups_without_duplicates() -> None:
    runner = _load_runner()

    expanded = runner.expand_suite_tokens(["providers", "xwiki", "retriever"])

    assert expanded.count("xwiki") == 1
    assert expanded.count("retriever") == 1
    assert set(expanded) == {"system-plugins", "web-search-internet", "retriever", "xwiki"}


def test_live_test_runner_builds_commands_and_default_env(monkeypatch) -> None:
    runner = _load_runner()
    monkeypatch.delenv("OPEN_TALON_XWIKI_USERNAME", raising=False)
    monkeypatch.delenv("OPEN_TALON_XWIKI_PASSWORD", raising=False)

    xwiki = runner.SUITES["xwiki"]
    command = runner.suite_command(xwiki)
    env = runner.suite_env(xwiki)

    assert command[1:4] == ["-m", "pytest", "-m"]
    assert "tests/infrastructure/test_xwiki_dossier_live_system.py" in command
    assert env["OPEN_TALON_RUN_XWIKI_LIVE"] == "1"
    assert env["OPEN_TALON_XWIKI_USERNAME"] == "superadmin"
    assert env["OPEN_TALON_XWIKI_PASSWORD"] == "system"


def test_live_test_runner_dry_run_keeps_stack_lifecycle_visible(capsys) -> None:
    runner = _load_runner()

    results = runner.run_plan(
        ["xwiki"],
        dry_run=True,
        fail_fast=True,
        keep_stack=False,
        extra_pytest_args=(),
    )

    output = capsys.readouterr().out
    assert "open-talon stop" in output
    assert "open-talon start --xwiki" in output
    assert "test_xwiki_dossier_live_system.py" in output
    assert results[0].suite == "xwiki"
    assert results[0].return_code == 0
