from __future__ import annotations

import json
import os
import sys


_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
if _CORE_COLLAB_DIR not in sys.path:
    sys.path.insert(0, _CORE_COLLAB_DIR)

from core_collab.repository import CollaborationRepository


def test_json_dumps_strips_postgres_incompatible_null_bytes() -> None:
    dumped = CollaborationRepository._json_dumps(
        {
            "plain": "before\x00after",
            "nested": [{"value": "\x00inner"}],
            "key\x00with_null": "value",
        }
    )

    assert "\x00" not in dumped
    assert "\\u0000" not in dumped
    decoded = json.loads(dumped)
    assert decoded["plain"] == "beforeafter"
    assert decoded["nested"][0]["value"] == "inner"
    assert decoded["keywith_null"] == "value"
