"""Anonymize a raw cloud dump before it may be committed as a test fixture.

Usage: python scripts/anonymize.py RAW.json OUT.json

Drops personal/identifying keys, zeroes installation ids and masks anything that looks like
an e-mail address, MAC address, JWT or UUID. Always read the output before committing it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

DROP_KEYS = {
    "macAddress", "serialNumber", "gatewaySerialNumber", "address", "location", "owner",
    "retailerId", "email", "access_token", "refresh_token", "id_token", "profile_info",
    "deviceId", "timeZoneId", "csrf", "transId",
}  # fmt: skip
ZERO_KEYS = {"installationId"}
NAME_KEYS = {"name"}  # replaced only on installation-like objects, see _is_installation

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_MAC = re.compile(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b")
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def _is_installation(obj: dict[str, Any]) -> bool:
    return "model" in obj and ("isOnline" in obj or "installationProfileId" in obj)


_MASKS = (
    (_JWT, "JWT-PLACEHOLDER"),
    (_EMAIL, "user@example.invalid"),
    (_MAC, "00:00:00:00:00:00"),
    (_UUID, "00000000-0000-0000-0000-000000000000"),
)


def _mask(text: str) -> str:
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


def anonymize(obj: Any) -> Any:
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        installation = _is_installation(obj)
        for key, value in obj.items():
            if key in DROP_KEYS:
                continue
            if key in ZERO_KEYS or (key == "id" and installation):
                result[key] = 0
            elif key == "name" and installation:
                result[key] = "Test installation"
            else:
                result[key] = anonymize(value)
        return result
    if isinstance(obj, list):
        return [anonymize(item) for item in obj]
    if isinstance(obj, str):
        return _mask(obj)
    return obj


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    data = json.loads(Path(argv[1]).read_text())
    Path(argv[2]).write_text(json.dumps(anonymize(data), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
