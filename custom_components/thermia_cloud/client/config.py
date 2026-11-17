"""Discovery of the cloud endpoints from the public ``/api/configuration``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .errors import ApiError, LoginFlowError, NetworkError

CONFIG_URL = "https://online.thermia.se/api/configuration"
REDIRECT_URI = "https://online.thermia.se/login"


@dataclass(frozen=True, slots=True)
class ThermiaConfig:
    """Endpoints and OAuth parameters advertised by the cloud."""

    api_base_url: str
    authority: str
    client_id: str
    scopes: tuple[str, ...]
    is_websocket_enabled: bool = False

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ThermiaConfig:
        try:
            auth = data["authConfig"]
            return cls(
                api_base_url=str(data["apiBaseUrl"]).rstrip("/"),
                authority=str(auth["authorities"]["signIn"]).rstrip("/"),
                client_id=str(auth["clientId"]),
                scopes=tuple(auth["scopes"]),
                is_websocket_enabled=bool(data.get("isWebSocketEnabled", False)),
            )
        except (KeyError, TypeError) as err:
            raise LoginFlowError(f"unexpected /api/configuration shape: {err!r}") from err


async def fetch_config(session: aiohttp.ClientSession) -> ThermiaConfig:
    """Download and parse the configuration (public, no auth)."""
    try:
        async with session.get(CONFIG_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise ApiError(resp.status, "configuration")
            return ThermiaConfig.from_json(await resp.json(content_type=None))
    except (aiohttp.ClientError, TimeoutError) as err:
        raise NetworkError(str(err)) from err
