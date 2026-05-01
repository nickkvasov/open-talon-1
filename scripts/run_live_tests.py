#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LiveSuite:
    name: str
    description: str
    paths: tuple[str, ...]
    stack_mode: str
    marker_expression: str | None = "integration"
    pytest_args: tuple[str, ...] = ("-q", "-s")
    env: Mapping[str, str] = field(default_factory=dict)
    default_env: Mapping[str, str] = field(default_factory=dict)


SUITES: dict[str, LiveSuite] = {
    "config": LiveSuite(
        name="config",
        description="Static local infrastructure config checks; no stack startup.",
        paths=(
            "tests/infrastructure/test_keycloak_local_config.py",
            "tests/infrastructure/test_memory_local_config.py",
            "tests/infrastructure/test_openbao_local_config.py",
            "tests/infrastructure/test_web_search_local_config.py",
            "tests/infrastructure/test_xwiki_local_config.py",
        ),
        stack_mode="none",
        marker_expression=None,
        pytest_args=("-q",),
    ),
    "compose": LiveSuite(
        name="compose",
        description="Raw Docker Compose infrastructure smoke tests; resets compose volumes.",
        paths=("tests/infrastructure/test_infrastructure.py",),
        stack_mode="self",
        pytest_args=("-v", "-s"),
    ),
    "mcp": LiveSuite(
        name="mcp",
        description="Live machine-identity and MCP gateway workflow tests.",
        paths=("tests/infrastructure/test_mcp_live_system.py",),
        stack_mode="self",
    ),
    "compaction": LiveSuite(
        name="compaction",
        description="Live runtime context compaction and persisted scratch tests.",
        paths=("tests/infrastructure/test_agent_compaction_live_system.py",),
        stack_mode="self",
    ),
    "tinker": LiveSuite(
        name="tinker",
        description="Live generated-tool authoring, approval, and execution tests.",
        paths=("tests/infrastructure/test_tinker_live_system.py",),
        stack_mode="self",
    ),
    "operational": LiveSuite(
        name="operational",
        description="Live managed operational-agent task and private MCP tests.",
        paths=("tests/infrastructure/operational_agents_live",),
        stack_mode="default",
        env={"OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE": "1"},
    ),
    "anchor": LiveSuite(
        name="anchor",
        description="Live Anchor publication-review and topic-moderation tests.",
        paths=("tests/infrastructure/anchor_live_system",),
        stack_mode="default",
        env={"OPEN_TALON_RUN_ANCHOR_LIVE": "1"},
    ),
    "retriever": LiveSuite(
        name="retriever",
        description="Live Retriever ingestion, embedding, search, PDF, and vision tests.",
        paths=("tests/infrastructure/test_retriever_live_system.py",),
        stack_mode="default",
        env={"OPEN_TALON_RUN_RETRIEVER_LIVE": "1"},
    ),
    "system-plugins": LiveSuite(
        name="system-plugins",
        description="Live System Plugin sync plus local web-search MCP tests.",
        paths=("tests/infrastructure/test_system_plugins_live_system.py",),
        stack_mode="self",
        env={"OPEN_TALON_RUN_SYSTEM_PLUGINS_LIVE": "1"},
    ),
    "web-search-internet": LiveSuite(
        name="web-search-internet",
        description="Live SearXNG-backed public internet search test.",
        paths=("tests/infrastructure/test_web_search_internet_live.py",),
        stack_mode="self",
        env={"OPEN_TALON_RUN_WEB_SEARCH_INTERNET_LIVE": "1"},
    ),
    "xwiki": LiveSuite(
        name="xwiki",
        description="Live XWiki-backed dossier provider and agent MCP workflow tests.",
        paths=("tests/infrastructure/test_xwiki_dossier_live_system.py",),
        stack_mode="xwiki",
        env={"OPEN_TALON_RUN_XWIKI_LIVE": "1"},
        default_env={
            "OPEN_TALON_XWIKI_USERNAME": "superadmin",
            "OPEN_TALON_XWIKI_PASSWORD": "system",
            "OPEN_TALON_XWIKI_STARTUP_WAIT_SECONDS": "240",
        },
    ),
}

SUITE_ORDER: tuple[str, ...] = (
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
)

GROUPS: dict[str, tuple[str, ...]] = {
    "all": SUITE_ORDER,
    "core": ("config", "compose", "mcp", "compaction"),
    "agents": ("operational", "anchor", "tinker", "compaction"),
    "providers": ("system-plugins", "web-search-internet", "retriever", "xwiki"),
    "default-stack": ("operational", "anchor", "retriever"),
    "web-search": ("system-plugins", "web-search-internet"),
    "knowledge": ("xwiki",),
}

STACK_PHASE_ORDER: tuple[str, ...] = ("none", "self", "default", "xwiki")
SENSITIVE_ENV_FRAGMENTS = ("PASSWORD", "SECRET", "TOKEN")


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    return_code: int
    duration_seconds: float


def emit(message: str = "") -> None:
    print(message, flush=True)


def python_executable() -> str:
    configured = os.getenv("PYTHON_BIN")
    if configured:
        return configured
    venv_python = ROOT_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def suite_env(suite: LiveSuite) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in suite.default_env.items():
        env.setdefault(key, value)
    env.update(suite.env)
    return env


def suite_command(suite: LiveSuite, extra_pytest_args: tuple[str, ...] = ()) -> list[str]:
    command = [python_executable(), "-m", "pytest"]
    if suite.marker_expression:
        command.extend(["-m", suite.marker_expression])
    command.extend(suite.paths)
    command.extend(suite.pytest_args)
    command.extend(extra_pytest_args)
    return command


def expand_suite_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        if token in GROUPS:
            expanded.extend(GROUPS[token])
        elif token in SUITES:
            expanded.append(token)
        else:
            valid = ", ".join(sorted([*SUITES.keys(), *GROUPS.keys()]))
            raise SystemExit(f"Unknown live-test suite or group {token!r}. Valid values: {valid}")

    requested = set(expanded)
    return [name for name in SUITE_ORDER if name in requested]


def _redacted_env_value(key: str, value: str) -> str:
    if any(fragment in key.upper() for fragment in SENSITIVE_ENV_FRAGMENTS):
        return "<set>"
    return value


def env_delta_for_display(suite: LiveSuite) -> str:
    keys = sorted(set(suite.default_env) | set(suite.env))
    if not keys:
        return ""
    effective = suite_env(suite)
    return " ".join(f"{key}={_redacted_env_value(key, effective[key])}" for key in keys)


def print_catalog() -> None:
    emit("Live test groups:")
    for name, suites in GROUPS.items():
        emit(f"  {name}: {', '.join(suites)}")
    emit()
    emit("Live test suites:")
    for name in SUITE_ORDER:
        suite = SUITES[name]
        emit(f"  {name} [{suite.stack_mode}]: {suite.description}")


def run_process(
    command: list[str],
    *,
    env: Mapping[str, str],
    dry_run: bool,
) -> int:
    if dry_run:
        emit("+ " + " ".join(command))
        return 0
    completed = subprocess.run(command, cwd=ROOT_DIR, env=dict(env), check=False)
    return int(completed.returncode)


def run_suite(
    suite: LiveSuite,
    *,
    dry_run: bool,
    extra_pytest_args: tuple[str, ...],
) -> SuiteResult:
    command = suite_command(suite, extra_pytest_args=extra_pytest_args)
    env = suite_env(suite)
    env_delta = env_delta_for_display(suite)
    emit(f"\n==> live suite: {suite.name}")
    if env_delta:
        emit(f"    env: {env_delta}")
    started = time.monotonic()
    return_code = run_process(command, env=env, dry_run=dry_run)
    return SuiteResult(
        suite=suite.name,
        return_code=return_code,
        duration_seconds=time.monotonic() - started,
    )


def stack_command(mode: str, action: str) -> list[str]:
    command = [str(ROOT_DIR / "open-talon"), action]
    if action == "start" and mode == "xwiki":
        command.append("--xwiki")
    return command


def run_stack_action(
    mode: str,
    action: str,
    *,
    env: Mapping[str, str],
    dry_run: bool,
) -> int:
    command = stack_command(mode, action)
    if dry_run:
        emit("+ " + " ".join(command))
        return 0
    completed = subprocess.run(command, cwd=ROOT_DIR, env=dict(env), check=False)
    return int(completed.returncode)


def run_managed_stack_phase(
    mode: str,
    suites: list[LiveSuite],
    *,
    dry_run: bool,
    fail_fast: bool,
    keep_stack: bool,
    extra_pytest_args: tuple[str, ...],
) -> list[SuiteResult]:
    if not suites:
        return []

    env = os.environ.copy()
    for suite in suites:
        for key, value in suite.default_env.items():
            env.setdefault(key, value)
        env.update(suite.env)

    emit(f"\n==> preparing {mode} live stack for: {', '.join(suite.name for suite in suites)}")
    stop_code = run_stack_action(mode, "stop", env=env, dry_run=dry_run)
    if stop_code != 0 and fail_fast:
        return [SuiteResult(f"{mode}:stop-before-start", stop_code, 0.0)]
    start_code = run_stack_action(mode, "start", env=env, dry_run=dry_run)
    if start_code != 0:
        return [SuiteResult(f"{mode}:start", start_code, 0.0)]

    results: list[SuiteResult] = []
    try:
        for suite in suites:
            result = run_suite(suite, dry_run=dry_run, extra_pytest_args=extra_pytest_args)
            results.append(result)
            if result.return_code != 0 and fail_fast:
                break
    finally:
        if not keep_stack:
            stop_after_code = run_stack_action(mode, "stop", env=env, dry_run=dry_run)
            if stop_after_code != 0:
                results.append(SuiteResult(f"{mode}:stop-after-run", stop_after_code, 0.0))
    return results


def run_plan(
    suite_names: list[str],
    *,
    dry_run: bool,
    fail_fast: bool,
    keep_stack: bool,
    extra_pytest_args: tuple[str, ...],
) -> list[SuiteResult]:
    suites_by_phase: dict[str, list[LiveSuite]] = {phase: [] for phase in STACK_PHASE_ORDER}
    for name in suite_names:
        suite = SUITES[name]
        suites_by_phase[suite.stack_mode].append(suite)

    results: list[SuiteResult] = []
    for phase in STACK_PHASE_ORDER:
        phase_suites = suites_by_phase[phase]
        if not phase_suites:
            continue
        if phase in {"default", "xwiki"}:
            phase_results = run_managed_stack_phase(
                phase,
                phase_suites,
                dry_run=dry_run,
                fail_fast=fail_fast,
                keep_stack=keep_stack,
                extra_pytest_args=extra_pytest_args,
            )
            results.extend(phase_results)
        else:
            for suite in phase_suites:
                result = run_suite(suite, dry_run=dry_run, extra_pytest_args=extra_pytest_args)
                results.append(result)
                if result.return_code != 0 and fail_fast:
                    return results
    return results


def print_summary(results: list[SuiteResult]) -> None:
    emit("\nLive test summary:")
    for result in results:
        status = "passed" if result.return_code == 0 else f"failed ({result.return_code})"
        emit(f"  {result.suite}: {status} in {result.duration_seconds:.1f}s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Open Talon live infrastructure tests as one matrix or as named fractions. "
            "Some suites self-manage ./open-talon; operational, Anchor, Retriever, and XWiki "
            "run against runner-managed shared stack phases."
        )
    )
    parser.add_argument(
        "suites",
        nargs="*",
        default=["all"],
        help="Suite or group names. Use --list to see valid values. Defaults to all.",
    )
    parser.add_argument("--list", action="store_true", help="List available suites and groups.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without executing them.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failing suite.",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Leave runner-managed default/XWiki stacks running after their phase.",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Extra argument appended to every pytest invocation. Repeat as needed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        print_catalog()
        return 0

    suite_names = expand_suite_tokens(args.suites)
    if not suite_names:
        parser.error("No live-test suites selected")
    emit(f"Selected live suites: {', '.join(suite_names)}")
    results = run_plan(
        suite_names,
        dry_run=bool(args.dry_run),
        fail_fast=bool(args.fail_fast),
        keep_stack=bool(args.keep_stack),
        extra_pytest_args=tuple(args.pytest_arg),
    )
    print_summary(results)
    return 1 if any(result.return_code != 0 for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
