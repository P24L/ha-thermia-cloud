"""Turn a downloaded integration diagnostics file into a test-fixture folder.

    python scripts/diagnostics_to_fixture.py diagnostics.json tests/fixtures/community/<name>

A user of another heat pump model downloads the diagnostics (*Settings -> Devices & services ->
Thermia Cloud -> the three dots -> Download diagnostics*) and attaches it to a *New model* issue.
The file is already redacted (no account, no ids, no MAC). This script rebuilds, for every
installation, the group files, the profile info and the history metadata in the layout the
planner tests read, so the dump can become a fixture and a golden file. One folder per
installation (``<name>`` for a single one, ``<name>_2`` ... for more). Read the result before
committing it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location("anonymize", Path(__file__).parent / "anonymize.py")
assert _spec and _spec.loader
_anonymize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_anonymize)


def _raw_register(spec: dict[str, Any], value: dict[str, Any] | None) -> dict[str, Any]:
    """A RegisterSpec dict (diagnostics) back into the shape the cloud sends."""
    return {
        "registerId": spec["register_id"],
        "registerIndex": spec["register_index"],
        "registerName": spec["name"],
        "groupName": spec["group_name"],
        "groupId": spec["group_id"],
        "presentation": spec["presentation"],
        "modifier": spec["modifier"],
        "unit": spec["unit"],
        "minValue": spec["min_value"],
        "maxValue": spec["max_value"],
        "step": spec["step"],
        "isReadOnly": spec["is_read_only"],
        "isInvisible": spec["is_invisible"],
        "trueText": spec["true_text"],
        "falseText": spec["false_text"],
        "valueNames": [
            {
                "name": v["name"],
                "value": v["value"],
                "visible": v["visible"],
                "isReadonly": v["is_readonly"],
                "confirmation": v["confirmation"],
            }
            for v in spec["value_names"]
        ],
        "registerValue": value["value"] if value else None,
        "stringRegisterValue": None,
        "timeStamp": value["timestamp"] if value else None,
    }


def convert(installation: dict[str, Any]) -> dict[str, Any]:
    """One installation entry of the diagnostics -> ``{file name: json}``."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for spec in installation["specs"]:
        value = installation["values"].get(f"{spec['name']}@{spec['group_name']}")
        groups[spec["group_name"]].append(_raw_register(spec, value))
    files: dict[str, Any] = {name: regs for name, regs in groups.items()}
    history = {
        "installationId": 0,
        "registers": [
            {
                "registerId": h["register_index"],
                "registerName": h["name"],
                "registerVisibilityCondition": h["visibility_condition"],
                "exclusiveVisibilityCondition": h["exclusive_visibility_condition"],
                "disabledRegisterValue": h["disabled_register_value"],
            }
            for h in installation["history"]
        ],
    }
    info = {
        "model": installation.get("model"),
        "firmware": installation.get("firmware"),
        "installationProfileId": installation.get("profile_id"),
        "hasIndoorTempSensor": installation.get("has_indoor_sensor"),
    }
    return {"groups": files, "history": history, "info": info}


def write(converted: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: Any) -> None:
        text = json.dumps(_anonymize.anonymize(data), indent=1, sort_keys=True, ensure_ascii=False)
        (out / name).write_text(text + "\n", encoding="utf-8")

    for name, registers in converted["groups"].items():
        dump(f"group_{name}.json", registers)
    dump("history_registers.json", converted["history"])
    dump("info.json", converted["info"])


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    base = Path(argv[2])
    for number, installation in enumerate(data["installations"], 1):
        folder = base if number == 1 else base.with_name(f"{base.name}_{number}")
        write(convert(installation), folder)
        print(f"{folder}: {len(installation['specs'])} registers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
