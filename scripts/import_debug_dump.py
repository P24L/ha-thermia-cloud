"""Turn a community debug dump (text file with printed JSON blocks) into a test-fixture folder.

    python scripts/import_debug_dump.py DUMP.txt tests/fixtures/community/<name>

The dump format is the one written by the python-thermia-online-api debug helper: sections
``self.__info:``, ``self.__status:``, ``self.__device_data:``, ``All available groups:`` and one
``Group <NAME>:`` block per group. Output: ``info.json``, ``status.json``, ``profile_groups.json``
and ``group_<NAME>.json`` for every group. Everything passes through ``scripts/anonymize.py``.
Read the result before committing it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location("anonymize", Path(__file__).parent / "anonymize.py")
assert _spec and _spec.loader
_anonymize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_anonymize)

_DECODER = json.JSONDecoder()


def _block(text: str, label: str) -> Any:
    start = text.index(label) + len(label)
    obj, _ = _DECODER.raw_decode(
        text, text.index("\n", start) + 1 if text[start] != "\n" else start + 1
    )
    return obj


def parse(text: str) -> dict[str, Any]:
    groups = {
        match.group(1): _block(text, match.group(0))
        for match in re.finditer(r"^Group (\S+):$", text, re.M)
    }
    return {
        "info": _block(text, "self.__info:"),
        "status": _block(text, "self.__status:"),
        "profile_groups": _block(text, "All available groups:"),
        "groups": groups,
    }


def write(parsed: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: Any) -> None:
        text = json.dumps(_anonymize.anonymize(data), indent=1, sort_keys=True, ensure_ascii=False)
        (out / name).write_text(text + "\n", encoding="utf-8")

    dump("info.json", parsed["info"])
    dump("status.json", parsed["status"])
    dump("profile_groups.json", parsed["profile_groups"])
    for name, registers in parsed["groups"].items():
        dump(f"group_{name}.json", registers)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    write(parse(Path(argv[1]).read_text(encoding="utf-8")), Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
