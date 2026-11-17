"""Sanity check that the committed fixtures load; replaced by real tests from Phase 2 on."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "itec_profile_1005"


def test_itec_fixture_has_26_registers() -> None:
    registers = [
        register
        for path in FIXTURES.glob("group_*.json")
        for register in json.loads(path.read_text())
    ]
    assert len(registers) == 26
