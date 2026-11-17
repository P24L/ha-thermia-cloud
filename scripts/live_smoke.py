"""Read-only smoke test against the real Thermia cloud.

Credentials come from THERMIA_USERNAME / THERMIA_PASSWORD only. Performs GET requests and
the login, nothing else. Prints no tokens, installation ids, names, MACs or addresses.

    python scripts/live_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.thermia_cloud.client.api import ThermiaApi
from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import fetch_config
from custom_components.thermia_cloud.client.errors import ThermiaError
from custom_components.thermia_cloud.client.http import ThermiaHttp


async def run() -> int:
    try:
        username, password = os.environ["THERMIA_USERNAME"], os.environ["THERMIA_PASSWORD"]
    except KeyError as err:
        print(f"Set {err.args[0]} in the environment first.")
        return 2

    async with aiohttp.ClientSession() as session:
        config = await fetch_config(session)
        print(f"websocket enabled: {config.is_websocket_enabled}")
        auth = ThermiaAuth(config, username, password)
        try:
            api = ThermiaApi(ThermiaHttp(session, auth, config.api_base_url))
            installations = await api.list_installations()
            print(f"{len(installations)} installation(s)")
            for number, inst in enumerate(installations, 1):
                detail = await api.get_installation(inst.id)
                print(
                    f"\n#{number}: model={inst.model} online={inst.is_online} "
                    f"firmware={inst.firmware_version} profile={detail.profile_id}"
                )
                groups = await api.get_groups(detail.profile_id)
                total = 0
                for group in groups:
                    registers = await api.get_group_registers(inst.id, group.name)
                    if not registers:
                        continue
                    print(f"  {group.name} (visibility={group.visibility})")
                    for spec, value in registers:
                        total += 1
                        rw = "ro" if spec.is_read_only else "rw"
                        limits = f"{spec.min_value}..{spec.max_value}"
                        stamp = value.timestamp.isoformat() if value.timestamp else "-"
                        print(
                            f"    {spec.name:38} {spec.presentation:20} {rw} {limits:12} "
                            f"= {value.value}  @ {stamp}"
                        )
                print(f"  -> {total} registers in {len(groups)} groups")
        finally:
            await auth.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except ThermiaError as err:
        print(f"{type(err).__name__}: {err}")
        sys.exit(1)
