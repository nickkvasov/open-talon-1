from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[3]


def load_repo_local_env(
    filenames: Iterable[str] = (".run/openai.env",),
) -> None:
    for relative_name in filenames:
        path = _REPO_ROOT / relative_name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if not name:
                continue
            os.environ.setdefault(name, value.strip())
