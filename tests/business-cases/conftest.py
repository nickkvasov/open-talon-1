from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest


_LOG_ROOT = Path(__file__).parent / "logs"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return normalized or "case"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture
def business_case_log_dir(request: pytest.FixtureRequest) -> Path:
    module_name = Path(str(request.node.fspath)).stem
    module_slug = _slugify(module_name.removeprefix("test_"))
    test_slug = _slugify(getattr(request.node, "originalname", None) or request.node.name)
    run_id = f"{_utc_stamp()}_pid{os.getpid()}"
    test_root = _LOG_ROOT / module_slug / test_slug
    run_dir = test_root / "runs" / run_id
    started_at = datetime.now(timezone.utc)

    manifest_path = run_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "module": module_name,
            "test_name": request.node.name,
            "nodeid": request.node.nodeid,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at.isoformat(),
            "log_files": [],
        },
    )

    yield run_dir

    log_files = sorted(path.name for path in run_dir.glob("*.jsonl"))
    finished_at = datetime.now(timezone.utc)
    report = getattr(request.node, "rep_call", None)
    status = "passed" if report is not None and report.passed else "failed"
    manifest = {
        "module": module_name,
        "test_name": request.node.name,
        "nodeid": request.node.nodeid,
        "run_id": run_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "log_files": log_files,
        "run_directory": str(run_dir.relative_to(_LOG_ROOT)),
    }
    _write_json(manifest_path, manifest)
    _write_json(
        test_root / "latest.json",
        {
            "latest_run_id": run_id,
            "latest_run_directory": str(run_dir.relative_to(_LOG_ROOT)),
            "latest_status": status,
            "updated_at": finished_at.isoformat(),
        },
    )
