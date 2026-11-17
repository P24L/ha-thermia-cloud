"""Golden-file helper shared by the planner tests."""

import json
import os
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def assert_golden(name: str, data: object) -> None:
    """Compare with ``golden/<name>.json``; run with ``UPDATE_GOLDEN=1`` to rewrite it.

    Plain JSON instead of a snapshot library: readable in a pull request and the same on every
    platform.
    """
    actual = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False, default=list) + "\n"
    path = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == actual, f"{name} changed (UPDATE_GOLDEN=1 to accept)"
