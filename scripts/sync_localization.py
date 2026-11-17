"""Download Thermia's label texts into the bundled snapshots (maintainer tool, needs credentials).

    THERMIA_USERNAME=... THERMIA_PASSWORD=... python scripts/sync_localization.py

Keeps only keys starting with ``REG_`` / ``COMP_`` (covers ``REG_GROUP_*`` and value names) plus
any value name found in the test fixtures; alarm and UI texts are not copied. Writes
``catalog/i18n/<culture>.json`` (sorted) and ``_meta.json``. Read-only against the cloud.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.thermia_cloud.client.api import ThermiaApi
from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import fetch_config
from custom_components.thermia_cloud.client.http import ThermiaHttp

OUT = ROOT / "custom_components" / "thermia_cloud" / "catalog" / "i18n"
FIXTURES = ROOT / "tests" / "fixtures"
PREFIXES = ("REG_", "COMP_")
TOOL = "sync_localization/1"


def fixture_value_names(directory: Path = FIXTURES) -> set[str]:
    names: set[str] = set()
    for path in directory.glob("*/group_*.json"):
        for register in json.loads(path.read_text()):
            names.update(v["name"] for v in register.get("valueNames") or ())
    return names


def filter_keys(resources: Mapping[str, str], extra_keys: Iterable[str] = ()) -> dict[str, str]:
    wanted = set(extra_keys)
    return {
        key: text
        for key, text in sorted(resources.items())
        if key.startswith(PREFIXES) or key in wanted
    }


async def run() -> int:
    try:
        username, password = os.environ["THERMIA_USERNAME"], os.environ["THERMIA_PASSWORD"]
    except KeyError as err:
        print(f"Set {err.args[0]} in the environment first.")
        return 2
    extra = fixture_value_names()
    OUT.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    async with aiohttp.ClientSession() as session:
        config = await fetch_config(session)
        auth = ThermiaAuth(config, username, password)
        try:
            api = ThermiaApi(ThermiaHttp(session, auth, config.api_base_url))
            cultures = [lang["culture"] for lang in await api.get_languages()]
            for culture in cultures:
                texts = filter_keys(await api.get_localization(culture), extra)
                counts[culture] = len(texts)
                (OUT / f"{culture}.json").write_text(
                    json.dumps(texts, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                print(f"{culture}: {len(texts)} keys")
        finally:
            await auth.close()
    meta = {
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Thermia Online localization endpoint (see NOTICE.md)",
        "tool": TOOL,
        "key_counts": counts,
    }
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
